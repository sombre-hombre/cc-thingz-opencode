"""Real launcher/revdiff in two owned invisible tmux PTYs; never human acceptance."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time


def probe(api, sid, run, env, live=False):
    root = Path(__file__).resolve().parents[2]
    folder = run / 'task5 launcher'
    folder.mkdir()
    socket = str(folder / 'tmux.sock')
    clean = dict(env, TERM='xterm-256color')
    command = ['/usr/bin/tmux', '-S', socket, '-f', '/dev/null']
    def tmux(*args):
        return subprocess.check_output(command + list(args), env=clean, text=True).strip()
    clients = []
    results = []
    try:
        for name in ('chosen', 'other'):
            tmux('new-session', '-d', '-s', name, '-x', '120', '-y', '40', 'sleep', '600')
            pid, fd = pty.fork()
            if pid == 0:
                os.execve(command[0], command + ['attach-session', '-t', name], clean)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
            clients.append((pid, fd))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            inventory = tmux('list-clients', '-F', '#{client_name}|#{session_name}')
            if len(inventory.splitlines()) == 2:
                break
            time.sleep(.1)
        names = dict(line.split('|', 1)[::-1] for line in inventory.splitlines())
        assert set(names) == {'chosen', 'other'}
        pane = tmux('display-message', '-p', '-t', 'chosen:0.0', '#{pane_id}')
        plan = folder / "external ' plan.md"
        plan.write_text('# TASK5_TARGET_ONLY\n\nFirst task\nLast line marker\n')
        for name, keys, annotations in [('annotation', b'q', True), ('empty-q', b'q', False),
                                         ('discard-Q', b'Qy', True)]:
            output = folder / (name + '.annotations')
            status = folder / (name + '.status.json')
            launch = shlex.join(['bash', str(root / 'plugins/planning/scripts/launch-plan-review.sh'),
                str(plan), '--output', str(output), '--status', str(status), '--tmux-socket', socket,
                '--tmux-client', names['chosen'], '--tmux-pane', pane,
                '--timeout', '30', '--exit-code-on-annotations'])
            responses = []
            def start():
                try:
                    responses.append(api('POST', f'/api/session/{sid}/shell', {'command': launch}))
                except Exception as exc:
                    responses.append(exc)
            thread = threading.Thread(target=start, daemon=True)
            thread.start()
            screens = [b'', b'']
            sent = False
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                for index, (_, fd) in enumerate(clients):
                    if select.select([fd], [], [], .05)[0]:
                        chunk = os.read(fd, 65536)
                        screens[index] += chunk
                        if b'\x1b[6n' in chunk:
                            os.write(fd, b'\x1b[1;1R')
                        if b']11;?' in chunk:
                            os.write(fd, b'\x1b]11;rgb:0000/0000/0000\x1b\\')
                if not sent and b'Last line marker' in screens[0]:
                    time.sleep(.5)
                    if annotations:
                        for part in (b'l', b'a', b'Task5 typed annotation', b'\r'):
                            os.write(clients[0][1], part)
                            time.sleep(.2)
                    for key in keys:
                        os.write(clients[0][1], bytes([key]))
                        time.sleep(.2)
                    sent = True
                if not thread.is_alive():
                    break
            thread.join(timeout=5)
            for index, screen in enumerate(screens):
                (folder / f'{name}-{index}.screen').write_bytes(screen)
            assert not thread.is_alive() and responses == [None], responses
            assert sent, 'full plan not rendered'
            assert b'TASK5_TARGET_ONLY' not in screens[1], 'wrong client received UI'
            data = json.loads(status.read_text())
            expected = 'annotations' if name == 'annotation' else 'needs-confirmation'
            assert data['state'] == expected, data
            assert data['revdiff_exit'] == (10 if name == 'annotation' else 0), data
            assert bool(output.read_bytes()) == (name == 'annotation')
            if name == 'annotation':
                assert 'Task5 typed annotation' in output.read_text()
                assert "external ' plan.md:1" in output.read_text()
            assert data['snapshot_text'] == plan.read_text()
            assert data['plan'] == str(plan)
            results.append({'probe': name, 'state': data['state'], 'exit': data['revdiff_exit']})
        # Preserve independent backend evidence even if an optional model fails.
        (folder / 'pty-results.json').write_text(json.dumps(results, indent=2) + '\n')
        if live:
            # Real slash -> skill -> failed launcher, not a simulated provider answer.
            session = api('POST', '/api/session', {'title': 'Task5 review-only failed target',
                'location': {'directory': str(folder)},
                'model': {'providerID': 'opencode', 'id': 'big-pickle'},
                'permissions': [{'action': 'subagent', 'resource': '*', 'effect': 'deny'}]})['data']['id']
            before = plan.read_bytes()
            api('POST', f'/api/session/{session}/command', {'name': 'review-plan', 'text':
                f'Existing plan: {plan}. Review-only, no edits or commits. User explicitly selected tmux '
                f'socket {folder / "nonexistent.sock"}, client /dev/pts/invalid, pane %999. '
                'Do not replace this target or launch any other UI. Attempt the launcher once, then report '
                'the actual incomplete/failed status and stop. Do not ask another question or start implementation. '
                'Write scratch files only inside your unique handoff directory; do not create global last-handoff files.'})
            api('POST', f'/api/experimental/session/{session}/wait', {})
            transcript = api('GET', f'/api/session/{session}/context')
            (folder / 'model-failed-target.json').write_text(json.dumps(transcript, indent=2))
            calls = [p for m in transcript['data'] for p in m.get('content', []) if p.get('type') == 'tool']
            assert any(p['name'] == 'skill' and p['state'].get('input') == {'id': 'make'}
                       and p['state']['status'] == 'completed' for p in calls), 'make not loaded'
            assert any(p['name'] == 'shell' and 'launch-plan-review.sh' in
                       p['state'].get('input', {}).get('command', '') for p in calls), 'launcher not called'
            assert not any(p['name'] in ('question', 'subagent', 'write', 'edit', 'patch') for p in calls), calls
            assert not [m for m in transcript['data'] if m.get('type') == 'idle' and m.get('error')], 'model/provider failed; see transcript'
            assert plan.read_bytes() == before
            results.append({'probe': 'model-review-only-failed-target', 'transcript': 'model-failed-target.json'})
        (folder / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        return results
    finally:
        if Path(socket).exists():
            subprocess.run(command + ['kill-server'], env=clean, capture_output=True)
        for pid, fd in clients:
            os.close(fd)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
