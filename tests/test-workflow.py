"""Runtime clipboard contracts: no desktop, clipboard reads or user config."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/workflow/scripts/clipboard.py"


class ClipboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workflow-", dir="/tmp/opencode")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.content = b'  title\r\n\n```sh\n$HOME `x` $(false)\nEOF\n```\n' + 'Привет 🌍\t'.encode()
        self.file = self.work / "text with spaces.txt"
        self.file.write_bytes(self.content)
        self.env = {"PATH": str(self.bin), "CAPTURE": str(self.work / "capture"),
                    "ARGS": str(self.work / "args"), "WAYLAND_DISPLAY": "fixture-only"}

    def backend(self, name):
        file = self.bin / name
        file.write_text(f'#!{sys.executable}\nimport json, os, pathlib, sys\n'
                        'pathlib.Path(os.environ["CAPTURE"]).write_bytes(sys.stdin.buffer.read())\n'
                        'pathlib.Path(os.environ["ARGS"]).write_text(json.dumps(sys.argv))\n'
                        'sys.stderr.write("fixture connection failed" if os.environ.get("FAIL") else "")\n'
                        'sys.exit(int(os.environ.get("FAIL", "0")))\n')
        file.chmod(0o755)

    def run_copy(self):
        return subprocess.run([sys.executable, str(HELPER), str(self.file)], env=self.env,
                              capture_output=True, text=True, timeout=4)

    def daemon_backend(self, *, parent_hangs=False):
        backend = self.bin / "wl-copy"
        backend.write_text(f'#!{sys.executable}\nimport os, pathlib, sys, time\n'
                           'pathlib.Path(os.environ["CAPTURE"]).write_bytes(sys.stdin.buffer.read())\n'
                           'pid = os.fork()\n'
                           'if pid == 0:\n'
                           '    time.sleep(30)  # inherit stdin/stdout/stderr like a selection owner\n'
                           '    os._exit(0)\n'
                           'pathlib.Path(os.environ["ARGS"]).write_text(str(pid))\n'
                           + ('time.sleep(30)\n' if parent_hangs else 'sys.exit(0)\n'))
        backend.chmod(0o755)

        def stop_daemon():
            pid_file = self.work / "args"
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.addCleanup(stop_daemon)

    def test_daemon_inherited_stdio_does_not_delay_success(self):
        self.daemon_backend()
        result = self.run_copy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "capture").read_bytes(), self.content)
        os.kill(int((self.work / "args").read_text()), 0)  # selection owner survives

    def test_timeout_with_daemon_inherited_stdio(self):
        self.daemon_backend(parent_hangs=True)
        spec = importlib.util.spec_from_file_location("clipboard", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module, "BACKEND_TIMEOUT", 0.2), patch.object(sys, "argv", [str(HELPER), str(self.file)]), patch.dict(os.environ, self.env, clear=True):
            from contextlib import redirect_stderr, redirect_stdout
            import io
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(module.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("wl-copy timed out", errors.getvalue())

    def test_wayland_preferred_and_exact_bytes(self):
        for name in ("wl-copy", "xclip", "xsel"):
            self.backend(name)
        result = self.run_copy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "capture").read_bytes(), self.content)
        self.assertIn(f"{len(self.content.decode())} characters; {len(self.content)} bytes", result.stdout)
        self.assertEqual(json.loads((self.work / "args").read_text())[1:], ["--type", "text/plain;charset=utf-8"])
        self.assertEqual(self.file.read_bytes(), self.content)

    def test_xclip_and_xsel_fallbacks(self):
        for backend, expected in (("xclip", ["-selection", "clipboard"]), ("xsel", ["--clipboard", "--input"])):
            with self.subTest(backend=backend):
                self.backend(backend)
                result = self.run_copy()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads((self.work / "args").read_text())[1:], expected)
                self.assertEqual((self.work / "capture").read_bytes(), self.content)
                (self.bin / backend).unlink()

    def test_non_wayland_ignores_wl_copy(self):
        self.backend("wl-copy")
        self.env.pop("WAYLAND_DISPLAY")
        self.assertNotEqual(self.run_copy().returncode, 0)

    def test_session_type_wayland(self):
        self.backend("wl-copy")
        self.env.pop("WAYLAND_DISPLAY")
        self.env["XDG_SESSION_TYPE"] = "wayland"
        self.assertEqual(self.run_copy().returncode, 0)

    def test_missing_and_failed_backend_not_success(self):
        missing = self.run_copy()
        self.assertEqual(missing.returncode, 1)
        self.assertIn("No clipboard backend found", missing.stderr)
        self.assertEqual(missing.stdout, "")
        self.backend("wl-copy")
        self.backend("xclip")
        self.env["FAIL"] = "23"
        failed = self.run_copy()
        self.assertEqual(failed.returncode, 1)
        self.assertIn("wl-copy failed (exit 23)", failed.stderr)
        self.assertEqual(failed.stdout, "")
        self.assertIn("wl-copy", json.loads((self.work / "args").read_text())[0])

    def test_missing_invalid_and_empty_input(self):
        self.backend("wl-copy")
        self.file.unlink()
        self.assertEqual(self.run_copy().returncode, 1)
        self.file.write_bytes(b"\xff")
        self.assertEqual(self.run_copy().returncode, 1)
        self.assertFalse((self.work / "capture").exists())
        self.file.write_bytes(b"")
        self.assertEqual(self.run_copy().returncode, 0)
        self.assertEqual((self.work / "capture").read_bytes(), b"")

    def test_mac_pbcopy_precedence(self):
        spec = importlib.util.spec_from_file_location("clipboard", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.backend("pbcopy")
        self.backend("wl-copy")
        with patch.object(sys, "platform", "darwin"), patch.object(sys, "argv", [str(HELPER), str(self.file)]), patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(module.main(), 0)
        self.assertEqual(json.loads((self.work / "args").read_text())[1:], [])
        self.assertEqual((self.work / "capture").read_bytes(), self.content)

    def test_symlinked_skill_resource_resolution(self):
        link = self.work / "installed skill"
        link.symlink_to(ROOT / "plugins/workflow/skills/txt-copy", target_is_directory=True)
        self.assertEqual((link.resolve() / "../../scripts/clipboard.py").resolve(), HELPER)


if __name__ == "__main__":
    unittest.main()
