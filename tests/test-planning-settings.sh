#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(sys.argv.pop())


class SettingsAndOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="settings space.", dir=os.environ.get("TMPDIR", "/tmp/opencode"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / "work space"
        self.work.mkdir()
        self.env = dict(os.environ, HOME=str(self.root / "home space"), XDG_CONFIG_HOME=str(self.root / "config space"))
        self.data = self.root / "config space/opencode/data/cc-thingz/planning"
        self.settings = self.data / "settings.json"
        self.project = self.work / ".opencode/exec-plan"
        self.scripts = ROOT / "plugins/planning/skills/exec/scripts"
        self.link = self.root / "linked scripts"
        self.link.mkdir()
        for name in ("resolve-file.sh", "customize-file.sh"):
            (self.link / name).symlink_to(self.scripts / name)
        self.reader = self.root / "linked settings.py"
        self.reader.symlink_to(ROOT / "scripts/read-planning-settings.py")

    def run_cmd(self, *args, ok=True):
        result = subprocess.run(args, cwd=self.work, env=self.env, text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.strip())
            self.assertEqual(result.stdout, "")
        return result

    def read(self, ok=True, *args):
        return self.run_cmd(sys.executable, str(self.reader), *args, ok=ok)

    def helper(self, name, *args, ok=True):
        return self.run_cmd("bash", str(self.link / (name + ".sh")), *args, ok=ok)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_defaults_and_no_seeding(self):
        expected = dict(external_review_cmd="", task_retries=1, review_iterations=5,
                        external_review_iterations=10, finalize_enabled=True, plans_dir="docs/plans")
        self.assertEqual(json.loads(self.read().stdout), expected)
        self.assertFalse(self.data.exists())
        original = (self.scripts.parent / "references/prompts/task.md").read_text()
        self.assertEqual(self.helper("resolve-file", "prompts/task.md").stdout, original)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.project.exists())

    def test_valid_types_zero_and_large_counts(self):
        values = dict(external_review_cmd="review --flag 'with spaces'", task_retries=0,
                      review_iterations=0, external_review_iterations=10000,
                      finalize_enabled=False, plans_dir="docs/my plans")
        self.write(self.settings, json.dumps(values))
        self.assertEqual(json.loads(self.read().stdout), values)

    def test_invalid_settings(self):
        cases = ["", "{broken", "[]", "null", '{"unknown":1}', '{"task_retries":NaN}']
        for key, bad_values in {
            "task_retries": [-1, 1.5, True, "1", None],
            "review_iterations": [-1, False, 2.0],
            "external_review_iterations": [-5, "10"],
            "finalize_enabled": [1, "false", None],
            "plans_dir": ["", "  ", "/absolute", "../escape", "docs/../escape", 3],
            "external_review_cmd": [False, [], 2],
        }.items():
            cases.extend(json.dumps({key: value}) for value in bad_values)
        for contents in cases:
            with self.subTest(contents=contents):
                self.write(self.settings, contents)
                self.assertIn(str(self.settings), self.read(ok=False).stderr)
        self.settings.write_bytes(b'\xff')
        self.read(ok=False)

    def test_settings_io_errors_and_explicit_file(self):
        self.settings.mkdir(parents=True)
        self.read(ok=False)
        self.settings.rmdir()
        self.settings.symlink_to(self.root / "missing")
        self.read(ok=False)
        self.settings.unlink()
        alternate = self.root / "chosen settings.json"
        self.write(alternate, '{"task_retries":2}')
        self.settings.symlink_to(alternate)
        self.assertEqual(json.loads(self.read().stdout)["task_retries"], 2)
        self.assertEqual(json.loads(self.read(True, str(alternate)).stdout)["task_retries"], 2)
        self.read(False, str(alternate), "extra")

    def test_xdg_home_and_user_only_command(self):
        marker = self.root / "executed"
        command = "touch " + str(marker)
        self.write(self.work / ".opencode/planning/settings.json", json.dumps(dict(external_review_cmd=command)))
        self.write(self.work / ".opencode/settings.json", json.dumps(dict(external_review_cmd=command)))
        self.write(self.work / "settings.json", json.dumps(dict(external_review_cmd=command)))
        self.assertEqual(json.loads(self.read().stdout)["external_review_cmd"], "")
        self.write(self.settings, json.dumps(dict(external_review_cmd=command)))
        self.assertEqual(json.loads(self.read().stdout)["external_review_cmd"], command)
        self.assertFalse(marker.exists())
        home_settings = Path(self.env["HOME"]) / ".config/opencode/data/cc-thingz/planning/settings.json"
        self.write(home_settings, '{"task_retries":3}')
        del self.env["XDG_CONFIG_HOME"]
        self.assertEqual(json.loads(self.read().stdout)["task_retries"], 3)
        self.env["XDG_CONFIG_HOME"] = ""
        self.assertEqual(json.loads(self.read().stdout)["task_retries"], 3)

    def test_override_precedence_including_empty_files(self):
        relative = "prompts/task.md"
        self.write(self.data / relative, "user")
        self.assertEqual(self.helper("resolve-file", relative).stdout, "user")
        self.write(self.project / relative, "project")
        self.assertEqual(self.helper("resolve-file", relative).stdout, "project")
        self.write(self.project / relative, "")
        self.assertEqual(self.helper("resolve-file", relative).stdout, "")
        (self.project / relative).unlink()
        self.write(self.data / relative, "")
        self.assertEqual(self.helper("resolve-file", relative).stdout, "")
        (self.data / relative).unlink()
        alternate = self.root / "alternate space"
        self.write(alternate / relative, "explicit")
        self.assertEqual(self.helper("resolve-file", relative, str(alternate)).stdout, "explicit")
        (self.project / relative).symlink_to(alternate / relative)
        self.assertEqual(self.helper("resolve-file", relative).stdout, "explicit")

    def test_resolution_errors(self):
        for args in [(), ("missing/file",), ("../escape",), ("prompts/../../escape",), ("/absolute",), ("..",)]:
            with self.subTest(args=args):
                self.helper("resolve-file", *args, ok=False)

    def test_relocated_skill_and_home_fallback(self):
        # A linked installation must not depend on the surrounding source checkout.
        installed = self.root / "relocated skill space"
        shutil.copytree(self.scripts.parent, installed)
        entry = self.root / "installed resolver"
        entry.symlink_to(installed / "scripts/resolve-file.sh")
        expected = (installed / "references/prompts/task.md").read_text()
        self.assertEqual(self.run_cmd("bash", str(entry), "prompts/task.md").stdout, expected)
        home_data = Path(self.env["HOME"]) / ".config/opencode/data/cc-thingz/planning"
        self.write(home_data / "prompts/task.md", "home override")
        self.env.pop("XDG_CONFIG_HOME")
        self.env["CLAUDE_PLUGIN_DATA"] = str(self.root / "ignored old config")
        self.assertEqual(self.helper("resolve-file", "prompts/task.md").stdout, "home override")
        self.env["XDG_CONFIG_HOME"] = ""
        self.assertEqual(self.helper("resolve-file", "prompts/task.md").stdout, "home override")
        self.helper("customize-file", "agents/quality.txt", "--user")
        self.assertTrue((home_data / "agents/quality.txt").is_file())

    def test_customize_exactly_one_file_and_no_overwrite(self):
        relative = "prompts/task.md"
        expected = (self.scripts.parent / "references" / relative).read_text()
        output = self.helper("customize-file", relative).stdout.strip()
        self.assertEqual(output, ".opencode/exec-plan/" + relative)
        self.assertEqual((self.project / relative).read_text(), expected)
        self.assertEqual(len(list(self.project.rglob("*.md"))), 1)
        self.helper("customize-file", relative, ok=False)
        self.assertEqual((self.project / relative).read_text(), expected)
        self.helper("customize-file", "agents/quality.txt", "--user")
        self.assertTrue((self.data / "agents/quality.txt").is_file())
        self.assertEqual(len(list(self.data.rglob("*.*"))), 1)
        alternate = self.root / "alternate space"
        self.helper("customize-file", relative, str(alternate) + "///")
        self.assertEqual((alternate / relative).read_text(), expected)

    def test_customize_errors_and_symlink_guards(self):
        for args in [(), ("../escape",), ("/absolute",), ("..",), ("missing",),
                     ("prompts/task.md", ""), ("prompts/task.md", "/")]:
            with self.subTest(args=args):
                self.helper("customize-file", *args, ok=False)
        outside = self.root / "outside"
        outside.mkdir()
        (self.work / ".opencode").symlink_to(outside)
        self.helper("customize-file", "prompts/task.md", ok=False)
        (self.work / ".opencode").unlink()
        self.project.mkdir(parents=True)
        (self.project / "prompts").symlink_to(outside)
        self.helper("customize-file", "prompts/task.md", ok=False)
        (self.project / "prompts").unlink()
        (self.project / "prompts").mkdir()
        (self.project / "prompts/task.md").symlink_to(outside / "missing")
        self.helper("customize-file", "prompts/task.md", ok=False)
        self.assertEqual(list(outside.iterdir()), [])
        # A user-selected root itself may be a symlink; nested components may not.
        user_link = self.root / "user link"
        user_link.symlink_to(outside)
        self.helper("customize-file", "prompts/task.md", str(user_link))
        self.assertTrue((outside / "prompts/task.md").is_file())
        (outside / "agents").symlink_to(self.root)
        self.helper("customize-file", "agents/quality.txt", str(user_link), ok=False)


unittest.main()
PY
