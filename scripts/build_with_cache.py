#!/usr/bin/env python3
"""Run a Zola content build with an automatically sized incremental cache."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys

MIB = 1024 * 1024


def read_int(path):
    try:
        value = int(Path(path).read_text().strip())
        return value if 0 <= value < 2**60 else None
    except (OSError, ValueError):
        return None


def cgroup_remaining(proc=Path('/proc'), root=Path('/sys/fs/cgroup')):
    """Inspect the process's cgroup and every enclosing memory limit."""
    values = []
    try:
        entries = (proc / 'self/cgroup').read_text().splitlines()
        mounts = (proc / 'self/mountinfo').read_text().splitlines()
        for entry in entries:
            _, controllers, group = entry.split(':', 2)
            v2 = not controllers
            if not v2 and 'memory' not in controllers.split(','):
                continue
            for mount in mounts:
                before, after = mount.split(' - ', 1)
                fields, fs = before.split(), after.split()
                if (v2 and fs[0] != 'cgroup2') or (not v2 and (fs[0] != 'cgroup' or 'memory' not in fs[2].split(','))):
                    continue
                mount_root, mount_point = Path(fields[3]), Path(fields[4])
                try:
                    relative = Path(group).relative_to(mount_root)
                except ValueError:
                    continue
                base = root / mount_point.relative_to('/sys/fs/cgroup')
                current = base / relative
                while True:
                    limit = read_int(current / ('memory.max' if v2 else 'memory.limit_in_bytes'))
                    used = read_int(current / ('memory.current' if v2 else 'memory.usage_in_bytes'))
                    if limit is not None and used is not None:
                        values.append(max(0, limit - used))
                    if current == base:
                        break
                    current = current.parent
    except (OSError, ValueError, IndexError):
        pass
    return min(values) if values else None


def detect_memory():
    sources = {}
    system = platform.system()
    if system == 'Linux':
        try:
            data = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
            for key, label in [('MemTotal', 'total'), ('MemAvailable', 'available')]:
                if key in data:
                    sources[label] = int(data[key].split()[0]) * 1024
        except (OSError, ValueError):
            pass
        remaining = cgroup_remaining()
        if remaining is not None:
            sources['cgroup_remaining'] = remaining
    elif system == 'Darwin':
        try:
            sources['total'] = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True))
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
    elif system == 'Windows':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            sources.update(total=status.total, available=status.available)
    return sources


def select_budget(sources):
    limits = [value // (4 if key == 'total' else 2) for key, value in sources.items()]
    return min(limits) // MIB if limits else 256


def command(binary, args, budget):
    # Normalize user flags to one unambiguous cache setting.
    result = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == '--cache-memory-limit':
            skip = True
        elif arg != '--incremental' and not arg.startswith('--cache-memory-limit='):
            result.append(arg)
    return [binary, 'build', '--incremental', '--cache-memory-limit', str(budget), *result]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default='zola')
    parser.add_argument('--cache-memory-limit', type=int, default=os.environ.get('ZOLA_CACHE_MEMORY_LIMIT_MIB'))
    options, args = parser.parse_known_args()
    if args[:1] == ['--']:
        args = args[1:]
    if options.cache_memory_limit is not None and options.cache_memory_limit < 0:
        parser.error('--cache-memory-limit must be nonnegative')
    sources = detect_memory()
    budget = options.cache_memory_limit if options.cache_memory_limit is not None else select_budget(sources)
    details = ', '.join(f'{key}={value // MIB} MiB' for key, value in sources.items()) or 'memory detection unavailable; conservative fallback'
    print(f'Incremental cache allowance: {budget} MiB ({details}); estimated retained cache, not total process memory', file=sys.stderr, flush=True)
    os.execvp(options.binary, command(options.binary, args, budget))


if __name__ == '__main__':
    main()
