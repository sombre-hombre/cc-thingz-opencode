#!/bin/bash
# exercise the review and completion commands documented by the exec skill

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$REPO_ROOT" <<'PY'
import os
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(sys.argv.pop())
EXEC = ROOT / "plugins/planning/skills/exec"
SKILL = (EXEC / "SKILL.md").read_text()
ACTIVE = (EXEC / "references/prompts/review-phases.md").read_text()


class PlanningPortTests(unittest.TestCase):
    def test_planning_resources_from_symlink_base(self):
        # V2 returns the symlink base, not its source. Reproduce the installed
        # layout with spaces; each required planning resource must resolve.
        with tempfile.TemporaryDirectory(prefix="planning resources ") as work:
            for group, name in (("brainstorm", "brainstorm"), ("planning", "make"), ("planning", "exec")):
                base = Path(work) / name
                base.symlink_to(ROOT / "plugins" / group / "skills" / name)
                canonical = base.resolve(strict=True)
                group_root = canonical.parent.parent
                for rel in ("scripts/resolve-rules.sh", "references/custom-rules.md"):
                    self.assertTrue((group_root / rel).is_file(), rel)
                if name == "make":
                    package = group_root.parent.parent
                    result = subprocess.run(["python3", str(package / "scripts/read-planning-settings.py")],
                                            capture_output=True, text=True, check=True)
                    self.assertEqual(json.loads(result.stdout)["plans_dir"], "docs/plans")
                    self.assertTrue((group_root / "skills/exec/scripts/run-external-review.sh").is_file())

    def test_active_planning_has_no_unresolved_claude_contracts(self):
        # Guard actual broken platform dependencies, not the wording of prompts.
        files = [ROOT / "plugins/brainstorm/skills/brainstorm/SKILL.md",
                 ROOT / "plugins/planning/skills/make/SKILL.md",
                 *sorted((ROOT / "plugins/planning/agents").glob("*.md")),
                 ROOT / "plugins/brainstorm/references/custom-rules.md",
                 ROOT / "plugins/planning/references/custom-rules.md",
                 EXEC / "references/prompts/task-loop.md",
                 EXEC / "references/prompts/task.md",
                 *sorted((EXEC / "references/prompts").glob("review*.md")),
                 *(EXEC / ("references/prompts/" + name + ".md") for name in ("fixer", "finalizer", "stats", "codex-review"))]
        for path in files:
            with self.subTest(path=path):
                text = path.read_text()
                self.assertIsNone(re.search(r"CLAUDE_PLUGIN|\$\{user_config\.|\$ARGUMENTS|AskUserQuestion|TodoWrite|multiSelect|subagent_type|/planning:", text))

    def test_external_json_argv_and_separate_output(self):
        # Real existing helper, controlled external binary. No model response
        # fixtures. A setting containing shell syntax must remain an argv value.
        with tempfile.TemporaryDirectory(prefix="external review ") as work:
            cwd = Path(work)
            reviewer = cwd / "reviewer"
            reviewer.write_text("#!/bin/bash\nprintf '%s' \"${@: -1}\"\nprintf 'MAJOR: stderr is not findings\\n' >&2\nexit \"$1\"\n")
            reviewer.chmod(0o755)
            env = dict(os.environ, PATH=str(cwd) + os.pathsep + os.environ["PATH"])
            for rc in (0, 7, 127):
                prompt = 'plan with spaces; $(touch MUST_NOT_EXIST) `false` "quoted"\nnext line'
                prompt_file = cwd / "prompt with spaces.txt"
                prompt_file.write_text(prompt)
                request = {"helper": str(EXEC / "scripts/run-external-review.sh"),
                           "command": f"reviewer {rc} ; touch MUST_NOT_EXIST", "cwd": work,
                           "prompt_file": str(prompt_file)}
                request_file = cwd / "request.json"
                request_file.write_text(json.dumps(request))
                decoded = json.loads(request_file.read_text())
                with (cwd / "review.out").open("w") as out, (cwd / "review.err").open("w") as err:
                    result = subprocess.run(["bash", decoded["helper"], decoded["command"],
                                             Path(decoded["prompt_file"]).read_text()],
                                            cwd=decoded["cwd"], env=env, stdin=subprocess.DEVNULL,
                                            stdout=out, stderr=err, timeout=5)
                self.assertEqual(result.returncode, rc)
                self.assertEqual((cwd / "review.out").read_text(), prompt)
                self.assertEqual((cwd / "review.err").read_text(), "MAJOR: stderr is not findings\n")
                self.assertFalse((cwd / "MUST_NOT_EXIST").exists())
            missing = subprocess.run(["bash", str(EXEC / "scripts/run-external-review.sh"),
                                      "absent-cc-thingz-reviewer", "review plan"],
                                     env=env, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 127)
            self.assertIn("run-external-review:", missing.stderr)
            self.assertEqual(missing.stdout, "")


class ExecWorkflowTests(unittest.TestCase):
    def test_review_templates_render_paths_rules_and_complete_findings_as_data(self):
        with tempfile.TemporaryDirectory() as work:
            context = Path(work) / "context.json"
            for name in ("review", "fixer", "finalizer", "stats", "codex-review"):
                template = EXEC / "references/prompts" / (name + ".md")
                slots = set(re.findall(r"\{\{([A-Z_]+)\}\}", template.read_text()))
                values = {k: "/absolute/path with spaces/" + k for k in slots}
                if "FINDINGS_LIST" in slots:
                    values["FINDINGS_LIST"] = "MAJOR: a:2 - $x `false`\nMINOR: duplicate\nMINOR: duplicate"
                if "USER_RULES" in slots:
                    values["USER_RULES"] = "literal {{FINDINGS_LIST}} stays data"
                context.write_text(json.dumps(values))
                result = subprocess.run(["python3", str(EXEC / "scripts/task-loop.py"), "render", str(template), str(context)],
                                        capture_output=True, text=True, check=True)
                for value in values.values():
                    self.assertIn(value, result.stdout)
                if "FINDINGS_LIST" in slots:
                    self.assertEqual(result.stdout.count("MINOR: duplicate"), 2)

    def test_external_review_includes_committed_fixes(self):
        with tempfile.TemporaryDirectory() as work:
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=work, env=env, check=True,
                    capture_output=True, text=True,
                ).stdout

            git("init", "-q", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            source = Path(work) / "code.txt"
            source.write_text("before\n")
            git("add", "code.txt")
            git("commit", "-qm", "Initial")
            git("switch", "-qc", "task")
            source.write_text("fixed\n")
            git("commit", "-qam", "Fix review finding")
            self.assertEqual(git("status", "--porcelain"), "")

            instruction = ACTIVE
            prompt = (EXEC / "references/prompts/codex-review.md").read_text()
            for name, text in (("exec skill", instruction), ("review prompt", prompt)):
                commands = re.findall(r"`(git diff[^`]*)`", text)
                self.assertTrue(commands, f"No review command found in {name}")
                for command in commands:
                    with self.subTest(source=name, command=command):
                        args = shlex.split(command.replace("DEFAULT_BRANCH", "main"))
                        self.assertIn("+fixed\n", git(*args[1:]))

    def test_completion_collects_timestamped_and_plain_decisions(self):
        with tempfile.TemporaryDirectory() as work:
            progress = Path(work) / "progress.txt"
            append = ["bash", str(EXEC / "scripts/append-progress.sh"), str(progress)]
            subprocess.run([*append, "task 1: completed"], check=True)
            for marker in ("decision", "deviation"):
                subprocess.run([*append, f"[{marker}] task 1: timestamped"], check=True)
            subprocess.run(
                append,
                input=(
                    "[decision] task 2: plain\n[deviation] task 2: plain\n"
                    "Review finding: quoted [decision] and [deviation] markers.\n"
                ),
                text=True, check=True,
            )
            expression = re.search(r"grep -E '([^']*decision[^']*)'", ACTIVE)
            self.assertIsNotNone(expression, "No completion collector found")
            result = subprocess.run(
                ["grep", "-E", expression.group(1), str(progress)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entries = [
                re.sub(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] ", "", line)
                for line in result.stdout.splitlines()
            ]
            self.assertEqual(entries, [
                "[decision] task 1: timestamped",
                "[deviation] task 1: timestamped",
                "[decision] task 2: plain",
                "[deviation] task 2: plain",
            ])


unittest.main(verbosity=2)
PY
