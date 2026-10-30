#!/usr/bin/env python3
"""Fresh low-memory broker: report INNER engine wait4 usage, not inherited RSS."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    evidence = Path(sys.argv[1])
    start = time.perf_counter()
    child = subprocess.Popen(sys.argv[2:])
    evidence.write_text(json.dumps({'child_pid': child.pid}))
    _, status, usage = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(status)
    evidence.write_text(json.dumps({'child_pid': child.pid, 'seconds': time.perf_counter()-start,
                                   'peak_rss_bytes': usage.ru_maxrss*1024,
                                   'cpu_user_seconds': usage.ru_utime, 'cpu_system_seconds': usage.ru_stime,
                                   'cpu_total_seconds': usage.ru_utime+usage.ru_stime,
                                   'exit_code': child.returncode}))
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
