"""Runtime external-Codex contract fixtures, not model-behavior assertions."""
import json
import os
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/planning/skills/exec/scripts/run-codex.sh"


class CodexContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="thinking-fixture.")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.env = {"PATH": str(self.bin) + os.pathsep + os.environ['PATH'], "HOME": str(self.work),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        subprocess.run(["git", "init", "-q", str(self.work)], env=self.env, check=True)
        self.source = self.work / "evidence.txt"
        self.source.write_text("unchanged evidence\n")
        # Log argv/stdin, keep response separate from diagnostic noise; no real model.
        cli = self.bin / "codex"
        cli.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
Path("argv.json").write_text(json.dumps(sys.argv[1:]))
assert sys.stdin.read() == "", "stdin was not EOF"
assert sys.argv[sys.argv.index("--sandbox")+1] == "read-only"
if os.environ.get("FAIL"):
    print("fixture auth failure", file=sys.stderr)
    sys.exit(23)
assert Path("evidence.txt").read_text() == "unchanged evidence\\n"
print("diagnostic only", file=sys.stderr)
print('{"verdict":"needs-attention","findings":[{"file":"evidence.txt","line_start":1,"confidence":0.9}]}')
''')
        cli.chmod(0o755)

    def call(self, **extra):
        return subprocess.run(["bash", str(HELPER), "Investigate evidence.txt:1; no edits"],
                              cwd=self.work, env={**self.env, **extra}, text=True, capture_output=True, timeout=10)

    def test_success_read_only_inherited_config_and_eof(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "needs-attention")
        self.assertEqual(result.stderr.strip(), "diagnostic only")
        argv = json.loads((self.work / "argv.json").read_text())
        self.assertFalse(any(a.startswith("model=") for a in argv))
        self.assertEqual(self.source.read_text(), "unchanged evidence\n")

    def test_override_one_argument_and_proxy_suppression(self):
        self.assertEqual(self.call(CODEX_MODEL="user model with spaces").returncode, 0)
        argv = json.loads((self.work / "argv.json").read_text())
        self.assertIn("model=user model with spaces", argv)
        self.assertEqual(self.call(CODEX_MODEL="override", CODEX_NO_OVERRIDES="1").returncode, 0)
        self.assertNotIn("-c", json.loads((self.work / "argv.json").read_text()))

    def test_failure_not_approval(self):
        result = self.call(FAIL="1")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, "")
        self.assertIn("auth failure", result.stderr)

    def test_missing_codex(self):
        (self.bin / "codex").unlink()
        # Deliberately restrict PATH so an installed real Codex cannot be used.
        for name in ("bash", "dirname", "readlink", "git", "python3"):
            (self.bin / name).symlink_to(sys.executable if name == 'python3' else shutil.which(name))
        self.env["PATH"] = str(self.bin)
        result = self.call()
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_zsh_background_recipe_preserves_real_exit(self):
        # zsh's read-only `status` caused a real live smoke failure. Exercise
        # success AND nonzero capture through the actual shell, not text matching.
        recipe = '''timeout_bin=$(command -v timeout || command -v gtimeout) || exit 127
"$timeout_bin" --signal=TERM --kill-after=1s 5s bash "$1" "$2" > codex.out 2> codex.err
codex_rc=$?
printf '%s\\n' "$codex_rc" > codex.status
exit "$codex_rc"
'''
        for fail, expected in (("", 0), ("1", 23)):
            result = subprocess.run([shutil.which("zsh"), "-c", recipe, "smoke", str(HELPER), "Read evidence.txt"],
                                    cwd=self.work, env={**self.env, "FAIL": fail}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual((self.work / "codex.status").read_text().strip(), str(expected))
            self.assertEqual(self.source.read_text(), "unchanged evidence\n")


if __name__ == "__main__":
    unittest.main()
