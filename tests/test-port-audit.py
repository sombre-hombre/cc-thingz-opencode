"""Mutation tests: reject damaged deliverables, not literary prompt variations."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audit', ROOT / 'tests/check-port.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('plugins', 'scripts', 'commands', 'integrations', 'tests'):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        for name in ('install-manifest.json', 'LICENSE', 'upstream.lock'):
            shutil.copyfile(ROOT / name, self.root / name)

    def check(self, needle):
        errors = audit.validate(self.root)['errors']
        self.assertTrue(any(needle in e for e in errors), errors)

    def manifest(self, mutate):
        p = self.root / 'install-manifest.json'
        data = json.loads(p.read_text())
        mutate(data)
        p.write_text(json.dumps(data))

    def test_valid(self):
        self.assertEqual(audit.validate(self.root)['errors'], [])

    def test_duplicate_and_unsafe_targets(self):
        self.manifest(lambda d: d['skills'][1].update(target='skills/brainstorm'))
        self.check('duplicate target')
        self.manifest(lambda d: d['skills'][1].update(target='../outside'))
        self.check('unsafe path')

    def test_missing_resource(self):
        (self.root / 'plugins/planning/skills/exec/scripts/task-loop.py').unlink()
        self.check('broken resource')

    def test_command_wrong_activation(self):
        p = self.root / 'commands/exec.md'
        p.write_text(p.read_text().replace('id: "exec"', 'id: "unknown"'))
        self.check('wrong skill activation')

    def test_active_vs_archived_tools(self):
        p = self.root / 'plugins/workflow/skills/wrong/SKILL.md'
        p.write_text(p.read_text() + '\n<!-- Task(subagent_type: old) -->\n')
        self.assertEqual(audit.validate(self.root)['errors'], [])
        p.write_text(p.read_text() + '\nTask(subagent_type: old)\n')
        self.check('obsolete tool schema')

    def test_hook_autoload(self):
        self.manifest(lambda d: d['plugins'][0].update(source='plugins/planning/hooks'))
        self.check('Claude autoload')

    def test_unmapped_skill(self):
        path = self.root / 'plugins/workflow/skills/extra'
        path.mkdir()
        (path / 'SKILL.md').write_text('---\nname: extra\ndescription: extra\n---\n')
        self.check('unmapped')

    def test_missing_mandatory_suite_and_license(self):
        (self.root / 'tests/test-exec-review.sh').unlink()
        self.check('missing mandatory suite')
        (self.root / 'LICENSE').write_text('changed')
        self.check('license changed')

    def test_source_symlink_escape(self):
        path = self.root / 'plugins/workflow/skills/external'
        path.symlink_to('/dev/null')
        self.manifest(lambda d: d['skills'][0].update(source=str(path.relative_to(self.root))))
        self.check('symlink escapes package')


if __name__ == '__main__':
    unittest.main()
