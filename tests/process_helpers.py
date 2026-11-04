"""POSIX process checks for tests; absence of Linux /proc is not success."""
import os
import subprocess
import time


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=2)
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return False
    if result.returncode:
        raise RuntimeError(result.stderr or 'ps failed')
    return bool(result.stdout.strip()) and not result.stdout.lstrip().startswith('Z')


def wait_stopped(pid, timeout=3):
    deadline = time.monotonic() + timeout
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    return not alive(pid)
