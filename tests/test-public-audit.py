"""Publication audit regressions use fabricated values, never real credentials."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_audit', ROOT / 'scripts/check-public.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        self.git('init', '-qb', 'main')
        self.git('config', 'user.name', 'sombre-hombre')
        self.git('config', 'user.email', audit.AUTHOR.split('<')[1].rstrip('>'))

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env, stderr=subprocess.PIPE)

    def test_clean_unborn_export_and_public_author(self):
        (self.root / 'README.md').write_text('Portable instructions use $HOME and paths resolved at runtime.\n')
        self.assertEqual(audit.audit(self.root)[0], [])
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'initial')
        errors, files, blobs = audit.audit(self.root, expected_author=audit.AUTHOR)
        self.assertEqual(errors, [])
        self.assertEqual((files, blobs), (1, 1))

    def test_deleted_data_remains_detected_in_history(self):
        # Construct a fictional personal path so the test itself is publishable.
        (self.root / 'note.txt').write_text('/' + 'home' + '/fixture-user/private')
        self.git('add', 'note.txt')
        self.git('commit', '-qm', 'fixture with private path')
        self.git('rm', 'note.txt')
        self.git('commit', '-qm', 'delete fixture')
        errors = audit.audit(self.root)[0]
        self.assertTrue(any('history blob' in error and 'personal home' in error for error in errors), errors)

    def test_secret_redacted_and_local_artifact_refused(self):
        fake = 'gh' + 'p_' + 'a' * 36
        (self.root / 'value.txt').write_text(fake)
        evidence = self.root / 'tests/smoke/evidence/example.json'
        evidence.parent.mkdir(parents=True)
        evidence.write_text('{}')
        errors = audit.audit(self.root)[0]
        self.assertTrue(any('GitHub credential' in error for error in errors), errors)
        self.assertTrue(any('local run artifact' in error for error in errors), errors)
        self.assertNotIn(fake, '\n'.join(errors))

    def test_tracked_credentials_are_not_hidden_by_ignore(self):
        (self.root / '.env').write_text('EXAMPLE=not-a-secret')
        self.git('add', '.env')
        (self.root / '.gitignore').write_text('.env\n')
        errors = audit.audit(self.root)[0]
        self.assertTrue(any('credential-like file' in error for error in errors), errors)

    def test_identity_check_is_opt_in_for_future_contributors(self):
        (self.root / 'code.txt').write_text('example')
        self.git('add', 'code.txt')
        self.git('config', 'user.name', 'Fixture contributor')
        self.git('config', 'user.email', 'contributor@example.invalid')
        self.git('commit', '-qm', 'fixture')
        self.assertEqual(audit.audit(self.root)[0], [])
        self.assertIn('history: unexpected author or committer identity', audit.audit(self.root, expected_author=audit.AUTHOR)[0])


if __name__ == '__main__':
    unittest.main()
