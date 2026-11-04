#!/usr/bin/env python3
"""Real revdiff + launcher worker in invisible PTYs, graphical launcher fixture only."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time


def terminal():
    argv = sys.argv[sys.argv.index('--') + 1:]
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(argv[0], argv)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
    screen = b''
    sent = False
    mode = os.environ['PROBE']
    started = time.monotonic()
    try:
        while time.monotonic() - started < 15:
            if select.select([fd], [], [], .1)[0]:
                try:
                    chunk = os.read(fd, 65536)
                    screen += chunk
                    Path(os.environ['SCREEN']).write_bytes(screen)
                    if b'\x1b[6n' in chunk:
                        os.write(fd, b'\x1b[1;1R')
                    if b']11;?' in chunk:
                        os.write(fd, b'\x1b]11;rgb:0000/0000/0000\x1b\\')
                except OSError:
                    pass
            if not sent and b'Last line marker' in screen and time.monotonic() - started > 1.5:
                if mode in ('annotation', 'discard'):
                    for key in (b'l', *([b'j'] * (int(os.environ.get('PROBE_ROW', '1')) - 1)),
                                b'a', b'No-tmux contract annotation', b'\r'):
                        os.write(fd, key)
                        time.sleep(.2)
                if mode == 'close':
                    os.kill(pid, signal.SIGHUP)
                else:
                    for key in (b'Q', b'y') if mode == 'discard' else (b'q',):
                        os.write(fd, key)
                        time.sleep(.1)
                sent = True
            ended, status = os.waitpid(pid, os.WNOHANG)
            if ended:
                return os.waitstatus_to_exitcode(status)
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        raise RuntimeError('PTY probe timed out')
    finally:
        Path(os.environ['SCREEN']).write_bytes(screen)
        os.close(fd)


def main():
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-no-tmux-pty.', dir='/tmp/opencode'))
    print(f'Artifacts: {run}', flush=True)
    bin_dir = run / 'bin'
    bin_dir.mkdir()
    # No compositor, Kitty process, tmux or desktop settings are touched.
    fixture = bin_dir / 'kitty'
    fixture.write_text('#!' + sys.executable + '\nimport runpy, sys\nsys.argv.insert(1, "--pty-terminal")\nrunpy.run_path('
                       + repr(str(Path(__file__).resolve())) + ', run_name="__main__")\n')
    fixture.chmod(0o755)
    assert shutil.which('revdiff'), 'missing revdiff'
    plan = run / "external ' plan.md"
    plan.write_text('# No-tmux plan\n\nFirst task\nLast line marker\n')
    results = []
    for mode in ('annotation', 'empty', 'discard', 'close'):
        output, status = run / f'{mode}.md', run / f'{mode}.json'
        screen = run / f'{mode}.screen'
        env = dict(os.environ, PATH=f'{bin_dir}:' + os.environ['PATH'],
                   PROBE=mode, SCREEN=str(screen), TERM='xterm-256color')
        env.pop('PLANNING_DISABLE_REVDIFF', None)
        args = ['bash', str(root / 'plugins/planning/scripts/launch-plan-review.sh'), str(plan),
                '--terminal', 'kitty-window', '--wayland-display', 'fixture-no-display',
                '--xdg-runtime-dir', str(run), '--output', str(output), '--status', str(status),
                '--exit-code-on-annotations', '--timeout', '20']
        process = subprocess.run(args, env=env, capture_output=True, timeout=30)
        data = json.loads(status.read_text())
        expected = {'annotation': 'annotations', 'empty': 'needs-confirmation',
                    'discard': 'needs-confirmation', 'close': 'cancelled'}[mode]
        assert data['state'] == expected, (mode, data, process.stderr)
        assert (process.returncode == 0) == (mode != 'close'), (mode, process.returncode)
        assert bool(output.read_text()) == (mode == 'annotation')
        assert b'Last line marker' in screen.read_bytes()
        results.append({'probe': mode, 'state': data['state'], 'exit': process.returncode,
                        'revdiff_exit': data['revdiff_exit']})
        (run / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    if '--pty-terminal' in sys.argv:
        sys.exit(terminal())
    main()
