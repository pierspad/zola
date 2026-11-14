import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import build_with_cache as cache


class CacheWrapperTests(unittest.TestCase):
    def test_budget(self):
        self.assertEqual(cache.select_budget({'total': 32 * 1024 * cache.MIB, 'available': 24 * 1024 * cache.MIB}), 8192)
        self.assertEqual(cache.select_budget({'total': 32 * 1024 * cache.MIB, 'cgroup_remaining': 1024 * cache.MIB}), 512)
        self.assertEqual(cache.select_budget({}), 256)
        self.assertEqual(cache.select_budget({'available': 0}), 0)

    def test_ancestor_cgroup(self):
        for v2 in (True, False):
            with self.subTest(v2=v2), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                proc, root = base / 'proc', base / 'cgroup'
                (proc / 'self').mkdir(parents=True)
                leaf = root / 'child'
                leaf.mkdir(parents=True)
                (proc / 'self/cgroup').write_text('0::/child\n' if v2 else '2:memory:/child\n')
                (proc / 'self/mountinfo').write_text('1 0 0:1 / /sys/fs/cgroup rw - ' + ('cgroup2 cgroup rw\n' if v2 else 'cgroup cgroup rw,memory\n'))
                limit, usage = ('memory.max', 'memory.current') if v2 else ('memory.limit_in_bytes', 'memory.usage_in_bytes')
                (root / limit).write_text('1000')
                (root / usage).write_text('900')
                (leaf / limit).write_text('2000')
                (leaf / usage).write_text('500')
                self.assertEqual(cache.cgroup_remaining(proc, root), 100)
                (root / limit).unlink()
                self.assertEqual(cache.cgroup_remaining(proc, root), 1500)

    def test_command_normalizes_flags(self):
        args = cache.command('zola', ['--incremental', '--cache-memory-limit=123', '--output-dir', 'out'], 0)
        self.assertEqual(args, ['zola', 'build', '--incremental', '--cache-memory-limit', '0', '--output-dir', 'out'])

    def test_explicit_and_environment_override_and_exec_status(self):
        with tempfile.TemporaryDirectory() as temp:
            helper = Path(temp) / 'zola_helper.py'
            helper.write_text('#!/usr/bin/env python3\nimport sys\nassert sys.argv[1:5] == ["build", "--incremental", "--cache-memory-limit", "0"]\nsys.exit(17)\n')
            helper.chmod(0o755)
            if os.name == 'nt':
                binary = Path(temp) / 'zola.cmd'
                binary.write_text(f'@"{sys.executable}" "{helper}" %*\r\n')
            else:
                binary = helper
            script = str(Path(cache.__file__))
            for flags, env in [(['--cache-memory-limit', '0'], os.environ.copy()), ([], dict(os.environ, ZOLA_CACHE_MEMORY_LIMIT_MIB='0'))]:
                result = subprocess.run([sys.executable, script, '--binary', str(binary), *flags], env=env, capture_output=True)
                self.assertEqual(result.returncode, 17, result.stderr)
            for value in ('-1', 'garbage'):
                result = subprocess.run([sys.executable, script, '--cache-memory-limit', value], capture_output=True)
                self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
