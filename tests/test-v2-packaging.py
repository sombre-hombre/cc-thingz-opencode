"""Packaging integrity, not tests of prose or simulated model behavior."""
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "install-manifest.json").read_text())

    def test_complete_unique_existing_mapping(self):
        skills = self.manifest["skills"]
        self.assertEqual(len(skills), 17)
        self.assertEqual(len({s["id"] for s in skills}), 17)
        sources = {str(p.parent.relative_to(ROOT)) for p in ROOT.glob("plugins/*/skills/*/SKILL.md")}
        self.assertEqual({s["source"] for s in skills}, sources)
        targets = []
        for group in ["skills", "commands", "agents"]:
            for entry in self.manifest[group]:
                source = ROOT / entry["source"]
                self.assertTrue(source.exists(), source)
                target = Path(entry["target"])
                self.assertFalse(target.is_absolute())
                self.assertNotIn("..", target.parts)
                targets.append(str(target))
        self.assertEqual(len(set(targets)), len(targets))
        release = next(s for s in skills if s["id"] == "release")
        self.assertEqual(release["upstreamID"], "new")
        self.assertEqual(release["source"], "plugins/release-tools/skills/release")
        self.assertTrue((ROOT / release["source"] / "scripts/calc-version.sh").is_file())

    def test_symlink_layout_preserves_supporting_files(self):
        with tempfile.TemporaryDirectory(prefix="packaging with spaces ") as directory:
            config = Path(directory)
            for group in ["skills", "commands", "agents"]:
                for entry in self.manifest[group]:
                    target = config / entry["target"]
                    source = ROOT / entry["source"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(source)
                    self.assertEqual(target.resolve(strict=True), source)
                    if group == "skills":
                        self.assertEqual((target / "SKILL.md").read_bytes(), (source / "SKILL.md").read_bytes())
                        for helper in source.glob("scripts/*"):
                            if helper.is_file():
                                self.assertEqual((target / "scripts" / helper.name).read_bytes(), helper.read_bytes())

    def test_command_targets_are_registered_skills_not_shell_blocks(self):
        command_ids = {Path(e["target"]).stem for e in self.manifest["commands"]}
        self.assertEqual(command_ids, {e["id"] for e in self.manifest["skills"]} | {"review-plan"})
        for entry in self.manifest["commands"]:
            text = (ROOT / entry["source"]).read_text()
            self.assertEqual(text.count("$ARGUMENTS"), 1)
            self.assertNotIn("!`", text, "untrusted arguments must never reach a template shell block")
            self.assertNotIn("$1", text, "full argument string must remain intact")
            self.assertIn("subagent: false", text)
        make = (ROOT / "plugins/planning/commands/make.md").read_text()
        self.assertLess(len(make), 800, "make wrapper accidentally duplicated workflow")
        self.assertTrue((ROOT / "plugins/planning/skills/make/SKILL.md").is_file())

    def test_no_hooks_or_upstream_plugins_are_install_entries(self):
        for group in ["skills", "commands", "agents"]:
            for entry in self.manifest[group]:
                self.assertNotIn("hooks", Path(entry["source"]).parts)
                self.assertNotIn(".claude-plugin", Path(entry["source"]).parts)
                self.assertNotIn("plugins", Path(entry["target"]).parts)
        for entry in self.manifest["plugins"]:
            self.assertEqual(Path(entry["source"]).parts[:2], ("integrations", "opencode"))
            package = ROOT / entry["source"]
            metadata = json.loads((package / "package.json").read_text())
            self.assertTrue((package / metadata["exports"]["."]).is_file())
            self.assertEqual(metadata["dependencies"]["@opencode/plugin"], "2.1.1")
            self.assertEqual(Path(entry["target"]).parts[0], "plugins")


if __name__ == "__main__":
    unittest.main()
