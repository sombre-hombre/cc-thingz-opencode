"""Platform contracts; Darwin fixtures are not actual macOS acceptance."""
import ctypes
import errno
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('portable_install', 'scripts/install.py')
launcher = load('portable_launcher', 'plugins/planning/scripts/plan-review-launcher.py')


class Portability(unittest.TestCase):
    def test_native_exclusive_rename_never_overwrites(self):
        with tempfile.TemporaryDirectory() as run:
            source, destination = Path(run) / 'source', Path(run) / 'destination'
            source.write_text('owned')
            destination.write_text('foreign')
            with self.assertRaises(FileExistsError):
                installer.rename_new(source, destination)
            self.assertEqual(destination.read_text(), 'foreign')
            self.assertEqual(source.read_text(), 'owned')
            destination.unlink()
            installer.rename_new(source, destination)
            self.assertEqual(destination.read_text(), 'owned')
            self.assertFalse(source.exists())

    def test_darwin_rename_exclusive_flag_errno_and_types(self):
        function = Mock(return_value=0)
        with patch.object(installer.sys, 'platform', 'darwin'), patch.object(installer.ctypes, 'CDLL', return_value=Mock(renamex_np=function)):
            installer.rename_new(Path('source'), Path('destination'))
            function.assert_called_once_with(b'source', b'destination', 4)
            self.assertEqual(function.argtypes, (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint))
            function.return_value = -1
            with patch.object(installer.ctypes, 'get_errno', return_value=errno.EEXIST):
                with self.assertRaises(FileExistsError):
                    installer.rename_new(Path('source'), Path('destination'))

    def test_no_unsafe_rename_fallback(self):
        with patch.object(installer.sys, 'platform', 'unsupported'):
            with self.assertRaises(OSError) as result:
                installer.rename_new(Path('source'), Path('destination'))
            self.assertEqual(result.exception.errno, errno.ENOTSUP)

    def test_process_detection_is_not_proc_dependent(self):
        self.assertTrue(launcher.alive(os.getpid()))
        with patch.object(launcher.os, 'kill', side_effect=ProcessLookupError):
            self.assertFalse(launcher.alive(1234))
        with patch.object(launcher.os, 'kill'), patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=0, stdout='Z', stderr='')):
            self.assertFalse(launcher.alive(1234))
        with patch.object(launcher.os, 'kill'), patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=2, stdout='', stderr='ps failed')):
            with self.assertRaises(OSError):
                launcher.alive(1234)

    def test_darwin_kitty_without_x11_and_foot_refusal(self):
        # Reuse actual terminal/revdiff fixture subprocesses, never a GUI.
        fixtures = load('plan_fixtures', 'tests/test-revdiff-plan.py')
        case = fixtures.Launcher()
        case.setUp()
        self.addCleanup(case.doCleanups)
        env = dict(case.env, FIXTURE_NATIVE_MAC='1')
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR'):
            env.pop(key, None)
        for terminal, expected in [('kitty-window', 0), ('foot-window', 1)]:
            args = case.argv(terminal=terminal)
            args = args[:args.index('--wayland-display')]
            script = 'import runpy,sys;sys.platform="darwin";sys.argv=sys.argv[1:];runpy.run_path(sys.argv[0],run_name="__main__")'
            result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'plugins/planning/scripts/plan-review-launcher.py'), *args[2:]], env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected == 0:
                self.assertFalse((case.run / 'annotations').read_bytes())
            case.clear_handoff()


if __name__ == '__main__':
    unittest.main()
