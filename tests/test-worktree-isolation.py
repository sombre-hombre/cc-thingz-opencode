#!/usr/bin/env python3
"""Real Git checkout/source tests; no mocked success or model calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/planning/skills/exec/scripts"
spec = importlib.util.spec_from_file_location("worktree", SCRIPTS / "worktree.py")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Isolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="worktree-tests.", dir="/tmp/opencode")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / "canonical checkout"
        self.main.mkdir()
        self.git(self.main, "init", "-q", "-b", "main")
        self.git(self.main, "config", "user.name", "Worktree test")
        self.git(self.main, "config", "user.email", "test@example.invalid")
        (self.main / "base").write_text("main\n")
        self.git(self.main, "add", "base")
        self.git(self.main, "commit", "-qm", "base")
        self.source = self.root / "feature source"
        self.git(self.main, "worktree", "add", "-qb", "existing-feature", str(self.source))
        self.plan = self.source / "docs/plans/20261103-two tasks.md"
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text("### Task 1: test\n- [ ] Isolated write\n")
        (self.source / "feature-only").write_text("feature\n")
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "feature plan")

    def git(self, source, *args):
        return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE)

    def cli(self, *args, env=None):
        return subprocess.run(["python3", str(SCRIPTS / "worktree.py"), *map(str, args)],
                              env=env, capture_output=True, text=True)

    def test_feature_head_collision_and_dirty_source(self):
        (self.source / "base").write_text("unstaged\n")
        (self.source / "staged foreign").write_text("staged\n")
        self.git(self.source, "add", "staged foreign")
        (self.source / "untracked foreign").write_bytes(b"foreign\x00bytes")
        self.git(self.source, "branch", "two-tasks", "main")
        before = helper.snapshot(self.source)
        canonical = helper.snapshot(self.main)
        result = self.cli("create", self.source, self.plan, self.root / "owned run")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        work = Path(record["directory"])
        self.assertTrue(record["branch"].startswith("two-tasks-"))
        self.assertEqual(self.git(work, "rev-parse", "HEAD").decode().strip(), before["head"])
        self.assertNotEqual(before["head"], canonical["head"])
        self.assertTrue((work / "feature-only").exists())
        self.assertFalse((work / "untracked foreign").exists())
        self.assertEqual((work / "base").read_text(), "main\n")
        (work / "child-only").write_text("worktree\n")
        self.assertFalse((self.source / "child-only").exists())
        self.assertEqual(helper.snapshot(self.source), before)
        self.assertEqual(helper.snapshot(self.main), canonical)
        verify = self.cli("verify", record["manifest"], work)
        self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_plan_prerequisites(self):
        for state in ("missing", "untracked", "modified", "staged", "external"):
            with self.subTest(state=state):
                plan = self.plan
                if state == "missing":
                    plan = self.source / "missing.md"
                elif state == "untracked":
                    plan = self.source / "untracked.md"
                    plan.write_text("untracked")
                elif state == "external":
                    plan = self.root / "external.md"
                    plan.write_text("external")
                else:
                    self.plan.write_text(state)
                    if state == "staged":
                        self.git(self.source, "add", str(self.plan))
                before = helper.snapshot(self.source)
                result = self.cli("create", self.source, plan, self.root / state)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / state).is_dir())
                self.assertEqual(helper.snapshot(self.source), before)

    def test_create_failure_retains_diagnostics_and_foreign_directory(self):
        shim = self.root / "shim"
        shim.mkdir()
        real_git = shutil.which("git")
        (shim / "git").write_text("#!/usr/bin/env python3\nimport os,sys\n"
            "if 'worktree' in sys.argv and 'add' in sys.argv:\n"
            " print('deliberate create failure', file=sys.stderr); sys.exit(42)\n"
            f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n")
        (shim / "git").chmod(0o755)
        before = helper.snapshot(self.source)
        run = self.root / "failed owned run"
        result = self.cli("create", self.source, self.plan, run,
                          env={**os.environ, "PATH": str(shim) + ":" + os.environ["PATH"]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deliberate create failure", result.stderr)
        record = json.loads((run / "worktree.json").read_text())
        self.assertEqual(record["state"], "failed")
        self.assertEqual(helper.snapshot(self.source), before)
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "keep").write_text("mine")
        result = self.cli("create", self.source, self.plan, foreign)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((foreign / "keep").read_text(), "mine")

    def test_move_failure_and_source_content_guard(self):
        record = helper.create(self.source, self.plan, self.root / "run")
        manifest = Path(record["manifest"])
        with self.assertRaisesRegex(ValueError, "session directory"):
            helper.verify(manifest, self.source)
        self.assertTrue(Path(record["directory"]).is_dir())
        self.assertEqual(json.loads(manifest.read_text())["state"], "created-session-move-pending")
        # Same status text, different dirty bytes must still fail the guard.
        (self.source / "untracked").write_text("first")
        before = helper.snapshot(self.source)
        (self.source / "untracked").write_text("second")
        self.assertEqual(helper.snapshot(self.source)["status_hex"], before["status_hex"])
        with self.assertRaisesRegex(ValueError, "source HEAD/branch/status/content"):
            helper.verify(manifest, Path(record["directory"]))

    def test_absolute_paths_and_source_containment(self):
        result = self.cli("create", self.source, self.plan, "relative-run")
        self.assertNotEqual(result.returncode, 0)
        result = self.cli("create", self.source, self.plan, self.source / "inside")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.source / "inside").exists())

    def test_source_guard_distinguishes_untracked_link_and_file(self):
        path = self.source / 'untracked link'
        path.symlink_to('target')  # Deliberately dangling; never dereference it.
        before = helper.snapshot(self.source)
        record = helper.create(self.source, self.plan, self.root / 'run')
        manifest, work = Path(record['manifest']), Path(record['directory'])
        self.assertEqual(helper.verify(manifest, work)['state'], 'verified')
        path.unlink()
        path.write_bytes(b'target')
        after = helper.snapshot(self.source)
        self.assertEqual(before['status_hex'], after['status_hex'])
        self.assertNotEqual(before['dirty_sha256'], after['dirty_sha256'])
        with self.assertRaisesRegex(ValueError, 'isolation breach'):
            helper.verify(manifest, work)
        path.unlink()
        path.symlink_to('target')
        self.assertEqual(helper.snapshot(self.source), before)
        self.assertEqual(helper.verify(manifest, work)['state'], 'verified')

    def test_source_guard_detects_untracked_permissions_change(self):
        path = self.source / 'untracked script'
        path.write_bytes(b'content')
        path.chmod(0o644)
        before = helper.snapshot(self.source)
        record = helper.create(self.source, self.plan, self.root / 'run')
        path.chmod(0o755)
        self.assertEqual(helper.snapshot(self.source)['status_hex'], before['status_hex'])
        with self.assertRaisesRegex(ValueError, 'isolation breach'):
            helper.verify(Path(record['manifest']), Path(record['directory']))

    def test_missing_target_plan_and_symlink_plan(self):
        link = self.source / "linked.md"
        link.symlink_to(self.plan)
        result = self.cli("create", self.source, link, self.root / "symlink-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        record = helper.create(self.source, self.plan, self.root / "run")
        Path(record["plan"]).unlink()
        with self.assertRaisesRegex(ValueError, "plan is missing"):
            helper.verify(Path(record["manifest"]), Path(record["directory"]))

    def test_invalid_ref_is_failure_not_silent_success(self):
        invalid = self.plan.with_name("bad:name.md")
        invalid.write_text(self.plan.read_text())
        self.git(self.source, "add", str(invalid))
        self.git(self.source, "commit", "-qm", "invalid branch basename")
        before = helper.snapshot(self.source)
        run = self.root / "invalid-run"
        result = self.cli("create", self.source, invalid, run)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid branch name", result.stderr)
        self.assertEqual(json.loads((run / "worktree.json").read_text())["state"], "failed")
        self.assertEqual(helper.snapshot(self.source), before)

    def test_branch_space_normalization_print_and_in_place(self):
        before = helper.snapshot(self.main)
        for name, expected in (("20261103-two tasks.md", "two-tasks"),
                               ("2026-11-03-keep-valid_name.md", "keep-valid_name"),
                               ("many  spaces\there.md", "many-spaces-here")):
            result = subprocess.check_output(["bash", str(SCRIPTS / "create-branch.sh"),
                                               "--print-name", name], cwd=self.main, text=True)
            self.assertEqual(result.strip(), expected)
        self.assertEqual(helper.snapshot(self.main), before)
        result = subprocess.check_output(["bash", str(SCRIPTS / "create-branch.sh"),
                                           "docs/a plan.md"], cwd=self.main, text=True)
        self.assertEqual(result.strip(), "a-plan")
        self.assertEqual(self.git(self.main, "branch", "--show-current").strip(), b"a-plan")


if __name__ == "__main__":
    unittest.main()
