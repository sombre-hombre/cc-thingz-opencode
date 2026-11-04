"""Launcher subprocess tests with terminal/revdiff fixtures, not UI acceptance."""
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from process_helpers import wait_stopped

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'plugins/planning/scripts/launch-plan-review.sh'

TMUX = '''#!/usr/bin/env python3
import os, subprocess, sys
from pathlib import Path
a = sys.argv[1:]
assert a[:2] == ['-S', '/explicit socket']
if a[2] == 'list-clients':
    print('/dev/pts/chosen\\t$1\\n/dev/pts/other\\t$2')
elif a[2] == 'display-message':
    print('%3\\t' + ('$2' if os.environ.get('MODE') == 'wrong-pane' else '$1'))
elif a[2] == 'display-popup':
    assert a[a.index('-c') + 1] == '/dev/pts/chosen'
    assert a[a.index('-t') + 1] == '%3'
    if os.environ.get('MODE') == 'terminal-fail':
        print('terminal error', file=sys.stderr)
        sys.exit(7)
    if os.environ.get('MODE') == 'close':
        sys.exit(0)
    sys.exit(subprocess.call(a[-1], shell=True))
else:
    raise AssertionError(a)
'''

REVDIFF = '''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
a = sys.argv[1:]
old = Path(a[a.index('--compare-old') + 1])
new = Path(a[a.index('--compare-new') + 1])
assert old.is_file() and not old.read_bytes()
assert new.read_bytes() == Path(os.environ['ORIGINAL']).read_bytes()
assert '--wrap' in a
assert '--only' not in a
Path(os.environ['READY']).write_text(str(os.getpid()))
m = os.environ.get('MODE', '')
if m == 'block':
    time.sleep(60)
if m == 'stale':
    Path(os.environ['ORIGINAL']).write_text('changed while reviewing')
if m in ('annotation', 'ten-no-flag', 'error-output'):
    Path(a[a.index('--output') + 1]).write_text('## ' + new.name + ':1 (+)\\n\\nRequested change\\n')
if m == 'error-output':
    print('reviewer error', file=sys.stderr)
    sys.exit(6)
if m in ('ten-no-flag', 'ten-empty') or (m == 'annotation' and '--exit-code-on-annotations' in a):
    sys.exit(10)
'''

TERMINAL = '''#!/usr/bin/env python3
import json, os, signal, subprocess, sys, time
from pathlib import Path
a = sys.argv[1:]
m = os.environ.get('TERMINAL_MODE', '')
if a[0] == '@':
    assert a[:3] == ['@', '--to', 'unix:/explicit kitty socket']
    if a[3] == 'ls':
        if m == 'remote-fail':
            sys.exit(9)
        print(json.dumps([{'tabs': [{'windows': [{'id': 42}, {'id': 99}]}]}]))
        sys.exit(0)
    if a[3] == 'close-window':
        assert a[4:] == ['--match', 'id:123']
        sys.exit(0)
    assert a[3:5] == ['launch', '--type'] and a[5] == 'overlay'
    assert a[a.index('--next-to') + 1] == 'id:42'
    assert a[a.index('--match') + 1] == 'window_id:42'
    assert a[a.index('--source-window') + 1] == 'id:42'
    child = subprocess.Popen(a[a.index('--') + 1:], start_new_session=True)
    print(123)
    sys.exit(0)
assert a[a.index('--title') + 1] == "plan: external ' plan.md"
if sys.platform != 'darwin' and os.environ.get('FIXTURE_NATIVE_MAC') != '1':
    assert os.environ['WAYLAND_DISPLAY'] == 'chosen-display'
    assert os.environ['XDG_RUNTIME_DIR'] == '/explicit runtime'
if m == 'fail':
    print('cannot connect to display', file=sys.stderr)
    sys.exit(8)
if m == 'close-before-worker':
    sys.exit(0)
child = subprocess.Popen(a[a.index('--') + 1:], start_new_session=True)
if m == 'daemon':
    sys.exit(0)
if m == 'close':
    ready = Path(os.environ['READY'])
    while not ready.exists():
        time.sleep(.01)
    child.send_signal(signal.SIGHUP)
sys.exit(child.wait())
'''


class Launcher(unittest.TestCase):
    def assert_process_stopped(self, pid):
        self.assertTrue(wait_stopped(pid), 'revdiff leaked after cancellation')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="plan-test ' spaces.", dir='/tmp/opencode')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.bin = self.run / 'bin'
        self.bin.mkdir()
        for name, text in [('tmux', TMUX), ('revdiff', REVDIFF), ('kitty', TERMINAL), ('foot', TERMINAL)]:
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        self.plan = self.run / "external ' plan.md"
        self.plan.write_text('# Full plan\nFirst\nLast marker\n')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        TMUX='/stale,1,0', KITTY_WINDOW_ID='wrong',
                        ORIGINAL=str(self.plan), READY=str(self.run / 'ready'))
        self.env.pop('PLANNING_DISABLE_REVDIFF', None)

    def argv(self, flag=True, target=True, terminal='tmux'):
        args = ['bash', str(LAUNCHER), str(self.plan), '--output', str(self.run / 'annotations'),
                '--status', str(self.run / 'status'), '--timeout', '5']
        if terminal != 'tmux':
            args += ['--terminal', terminal, '--wayland-display', 'chosen-display',
                     '--xdg-runtime-dir', '/explicit runtime']
            if terminal == 'kitty-overlay' and target:
                args += ['--kitty-socket', 'unix:/explicit kitty socket', '--kitty-window-id', '42']
        elif target:
            args += ['--tmux-socket', '/explicit socket', '--tmux-client', '/dev/pts/chosen',
                     '--tmux-pane', '%3']
        if flag:
            args += ['--exit-code-on-annotations']
        return args

    def launch(self, mode='', **kwargs):
        result = subprocess.run(self.argv(**kwargs), env=dict(self.env, MODE=mode),
                                capture_output=True, timeout=12)
        self.assertEqual(result.stdout, b'')
        status = json.loads((self.run / 'status').read_text())
        return result, status, (self.run / 'annotations').read_text()

    def test_empty_needs_confirmation_and_cleanup(self):
        before = set(Path('/tmp/opencode').glob('plan-review-*'))
        result, status, output = self.launch()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'needs-confirmation')
        self.assertEqual(output, '')
        self.assertEqual(status['snapshot_text'], self.plan.read_text())
        self.assertEqual(status['snapshot_sha256'], hashlib.sha256(self.plan.read_bytes()).hexdigest())
        self.assertEqual(set(Path('/tmp/opencode').glob('plan-review-*')), before)

    def test_annotations_both_flag_modes(self):
        for flag in (True, False):
            with self.subTest(flag=flag):
                result, status, output = self.launch('annotation', flag=flag)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(status['state'], 'annotations')
                self.assertEqual(status['revdiff_exit'], 10 if flag else 0)
                self.assertEqual(status['plan'], str(self.plan))
                self.assertIn("external ' plan.md:1", output)
                (self.run / 'annotations').unlink()
                (self.run / 'status').unlink()

    def test_confirmation_rechecks_after_waiting_for_user(self):
        result, status, _ = self.launch()
        self.assertEqual(result.returncode, 0)
        check = ['python3', str(LAUNCHER.with_name('plan-review-launcher.py')),
                 '--check-status', str(self.run / 'status')]
        self.assertEqual(subprocess.run(check, capture_output=True).returncode, 0)
        # Launcher already returned; user has not confirmed yet.
        self.plan.write_text(self.plan.read_text() + 'late user edit\n')
        result = subprocess.run(check, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'stale')

    def test_errors_never_clean(self):
        for mode in ('terminal-fail', 'wrong-pane', 'ten-no-flag', 'error-output', 'close', 'stale'):
            with self.subTest(mode=mode):
                result, status, output = self.launch(mode, flag=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(status['state'], ('failed', 'cancelled', 'stale'))
                self.assertFalse(output)
                if mode == 'error-output':
                    self.assertIn('reviewer error', status['revdiff_stderr'])
                if mode == 'terminal-fail':
                    self.assertIn('terminal error', status['terminal_stderr'])
                (self.run / 'annotations').unlink()
                (self.run / 'status').unlink()

    def test_stale_server_env_is_not_target(self):
        result, status, _ = self.launch(target=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')
        self.assertIn('explicit', status['reason'])
        self.assertFalse((self.run / 'ready').exists())

    def test_exit_ten_requires_annotations_even_with_flag(self):
        result, status, output = self.launch('ten-empty')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')
        self.assertFalse(output)

    def test_missing_dependencies_and_plan(self):
        (self.bin / 'revdiff').unlink()
        for name in ('bash', 'python3', 'readlink', 'dirname'):
            (self.bin / name).symlink_to(shutil.which(name))
        self.env['PATH'] = str(self.bin)
        result, status, _ = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing dependency: revdiff', status['reason'])
        (self.run / 'annotations').unlink()
        (self.run / 'status').unlink()
        self.plan.unlink()
        result, status, _ = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')

    def test_no_overwrite_stale_handoff(self):
        (self.run / 'annotations').write_text('old annotations')
        result = subprocess.run(self.argv(), env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.run / 'annotations').read_text(), 'old annotations')

    def test_cancel_and_timeout_cleanup_child(self):
        for cancel in (True, False):
            with self.subTest(cancel=cancel):
                args = self.argv()
                if not cancel:
                    args[args.index('--timeout') + 1] = '.4'
                process = subprocess.Popen(args, env=dict(self.env, MODE='block'),
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deadline = time.monotonic() + 5
                while not (self.run / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((self.run / 'ready').exists())
                child = int((self.run / 'ready').read_text())
                if cancel:
                    process.send_signal(signal.SIGTERM)
                out, _ = process.communicate(timeout=10)
                self.assertFalse(out)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'cancelled')
                self.assert_process_stopped(child)
                for name in ('annotations', 'status', 'ready'):
                    (self.run / name).unlink()

    def test_full_text_for_all_git_states_and_symlink_entrypoint(self):
        subprocess.run(['git', 'init', '-q', str(self.run)], check=True)
        subprocess.run(['git', '-C', str(self.run), 'add', self.plan.name], check=True)
        subprocess.run(['git', '-C', str(self.run), '-c', 'user.name=Test', '-c',
                        'user.email=test@example.invalid', 'commit', '-qm', 'plan'], check=True)
        link = self.run / 'launcher link'
        link.symlink_to(LAUNCHER)
        for kind in ('committed', 'modified', 'untracked'):
            if kind == 'modified':
                self.plan.write_text(self.plan.read_text() + 'A newer line\n')
            if kind == 'untracked':
                subprocess.run(['git', '-C', str(self.run), 'rm', '--cached', self.plan.name], check=True,
                               capture_output=True)
            args = self.argv()
            args[1] = str(link)
            result = subprocess.run(args, env=self.env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((self.run / 'status').read_text())['snapshot_text'], self.plan.read_text())
            for name in ('annotations', 'status'):
                (self.run / name).unlink()

    def clear_handoff(self):
        for name in ('annotations', 'status', 'ready'):
            (self.run / name).unlink(missing_ok=True)

    def test_no_tmux_backends_result_contract(self):
        # No tmux executable is available; stale KITTY/TMUX env remains present.
        (self.bin / 'tmux').unlink()
        for terminal in (('kitty-window', 'kitty-overlay') if sys.platform == 'darwin' else ('kitty-window', 'foot-window', 'kitty-overlay')):
            for mode in ('', 'annotation', 'error-output', 'ten-empty', 'stale'):
                with self.subTest(terminal=terminal, mode=mode):
                    self.env['TERMINAL_MODE'] = 'daemon' if terminal != 'kitty-overlay' else ''
                    result, status, output = self.launch(mode, terminal=terminal)
                    self.assertEqual(status['terminal']['backend'], terminal)
                    if mode in ('', 'annotation'):
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(status['state'], 'annotations' if mode else 'needs-confirmation')
                        self.assertEqual(bool(output), mode == 'annotation')
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(output)
                    self.clear_handoff()
                    self.plan.write_text('# Full plan\nFirst\nLast marker\n')

    def test_no_tmux_close_failure_and_timeout(self):
        for terminal in (('kitty-window', 'kitty-overlay') if sys.platform == 'darwin' else ('kitty-window', 'foot-window', 'kitty-overlay')):
            for mode in ('fail', 'close', 'timeout') if terminal != 'kitty-overlay' else ('remote-fail', 'timeout'):
                with self.subTest(terminal=terminal, mode=mode):
                    self.env['TERMINAL_MODE'] = mode
                    args = self.argv(terminal=terminal)
                    args[args.index('--timeout') + 1] = '1'
                    process = subprocess.run(args, env=dict(self.env, MODE='block'), capture_output=True, timeout=10)
                    status = json.loads((self.run / 'status').read_text())
                    self.assertNotEqual(process.returncode, 0)
                    self.assertIn(status['state'], ('failed', 'cancelled'))
                    self.assertFalse((self.run / 'annotations').read_bytes())
                    if (self.run / 'ready').exists():
                        pid = int((self.run / 'ready').read_text())
                        self.assert_process_stopped(pid)
                    if mode == 'fail':
                        self.assertIn('cannot connect to display', status['terminal_stderr'])
                        self.assertEqual(status['terminal_exit'], 8)
                    self.clear_handoff()

    def test_no_tmux_missing_target_display_and_early_exit(self):
        result, status, _ = self.launch(terminal='kitty-overlay', target=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('explicit', status['reason'])
        self.clear_handoff()
        args = self.argv(terminal='kitty-window')
        args = args[:args.index('--wayland-display')]  # no display overrides
        env = dict(self.env)
        for key in ('WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR'):
            env.pop(key, None)
        result = subprocess.run(args, env=env, capture_output=True)
        if sys.platform == 'darwin':
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'needs-confirmation')
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('display unavailable', json.loads((self.run / 'status').read_text())['reason'])
        self.clear_handoff()
        self.env['TERMINAL_MODE'] = 'close-before-worker'
        result, status, _ = self.launch(terminal='kitty-window')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'cancelled')  # deadline, not a clean terminal exit

    def test_no_tmux_signal_cleans_worker(self):
        for terminal in ('kitty-window', 'kitty-overlay'):
            with self.subTest(terminal=terminal):
                self.env['TERMINAL_MODE'] = 'daemon'
                process = subprocess.Popen(self.argv(terminal=terminal), env=dict(self.env, MODE='block'),
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deadline = time.monotonic() + 5
                while not (self.run / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((self.run / 'ready').exists())
                pid = int((self.run / 'ready').read_text())
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130)
                self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'cancelled')
                self.assert_process_stopped(pid)
                self.clear_handoff()

    def test_backend_alias_and_invalid_overlay_id(self):
        args = self.argv(terminal='kitty-window')
        args[args.index('--terminal')] = '--backend'
        result = subprocess.run(args, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'needs-confirmation')
        self.clear_handoff()
        for window_id in ('404', '-1'):
            args = self.argv(terminal='kitty-overlay')
            args[args.index('--kitty-window-id') + 1] = window_id
            result = subprocess.run(args, env=self.env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads((self.run / 'status').read_text())['state'], 'failed')
            self.assertFalse((self.run / 'ready').exists())
            self.clear_handoff()

    def test_missing_graphical_executable_has_no_silent_fallback(self):
        (self.bin / 'kitty').unlink()
        for name in ('bash', 'python3', 'readlink', 'dirname'):
            (self.bin / name).symlink_to(shutil.which(name))
        self.env['PATH'] = str(self.bin)
        result, status, output = self.launch(terminal='kitty-window')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing dependency: kitty', status['reason'])
        self.assertFalse(output)
        self.assertFalse((self.run / 'ready').exists())


if __name__ == '__main__':
    unittest.main()
