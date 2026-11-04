#!/usr/bin/env python3
"""Installer result/error tests; no real user configuration or service access."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cc-thingz-install-test.', dir='/tmp/opencode')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'source with spaces'
        self.source.mkdir()
        for n in ('plugins', 'commands', 'scripts', 'integrations'):
            shutil.copytree(ROOT / n, self.source / n, ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
        for n in ('install-manifest.json', 'LICENSE', 'upstream.lock'):
            shutil.copy2(ROOT / n, self.source / n)
        sdk = self.source / 'integrations/opencode/skill-eval/node_modules/@opencode/plugin'
        sdk.mkdir(parents=True)
        (sdk / 'package.json').write_text('{"version":"2.1.1"}')
        self.target = self.base / 'xdg/opencode'
        self.target.mkdir(parents=True)
        self.state = self.base / 'state'
        self.env = dict(os.environ, HOME=str(self.base / 'home'), XDG_CONFIG_HOME=str(self.base / 'xdg'))

    def run_install(self, action='install', *extra, ok=True, target=True):
        argv = ['python3', str(self.source / 'scripts/install.py'), action, '--state-dir', str(self.state)]
        if target:
            argv += ['--target-root', str(self.target)]
        p = subprocess.run(argv + list(extra), env=self.env, text=True, capture_output=True)
        self.assertEqual(p.returncode == 0, ok, p.stderr)
        return json.loads(p.stdout) if p.returncode == 0 else p.stderr

    def old(self):
        p = self.target / 'skills/exec'
        p.mkdir(parents=True)
        (p / 'SKILL.md').write_text('old actual installation\n')
        (self.target / 'plugins').mkdir()
        (self.target / 'plugins/plan-annotate-hook.ts').write_text('old hook')
        (self.target / 'data').mkdir()
        (self.target / 'data/personal').write_text('deliberate user rules')
        inv = self.base / 'approved.json'
        inv.write_text(json.dumps(self.run_install('inventory')))
        return inv

    def test_first_repeat_xdg_restore_and_foreign_files(self):
        (self.target / 'opencode.json').write_text('unrelated secret untouched')
        before = installer.fingerprint(self.target / 'opencode.json')
        first = self.run_install(target=False)
        self.assertEqual(first['status'], 'installed')
        self.assertEqual(self.run_install()['status'], 'unchanged')
        (self.target / 'commands/foreign.md').write_text('new foreign work')
        self.run_install('restore')
        self.assertEqual(installer.fingerprint(self.target / 'opencode.json'), before)
        self.assertTrue((self.target / 'commands/foreign.md').is_file())
        self.assertFalse((self.target / 'skills/exec').exists())
        self.assertEqual(self.run_install('restore')['status'], 'already-restored')

    def test_backup_and_exact_legacy_restore(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        result = self.run_install('install', '--replace-inventory', str(inv))
        self.assertFalse((self.target / 'plugins/plan-annotate-hook.ts').exists())
        self.assertEqual((Path(result['backup']) / 'data/personal').read_text(), 'deliberate user rules')
        self.run_install('restore')
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_conflicts_and_stale_inventory_do_not_touch_any_entry(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        self.run_install(ok=False)
        self.assertEqual(installer.fingerprint(self.target), before)
        (self.target / 'skills/exec/foreign').write_text('new work')
        before = installer.fingerprint(self.target)
        self.run_install('install', '--replace-inventory', str(inv), ok=False)
        self.assertEqual(installer.fingerprint(self.target), before)
        (self.target / 'commands').mkdir()
        (self.target / 'commands/release.md').write_text('foreign command')
        inv.write_text(json.dumps(self.run_install('inventory')))
        self.run_install('install', '--replace-inventory', str(inv), ok=False)

    def test_foreign_modification_blocks_restore_and_repeat(self):
        self.run_install()
        entry = self.target / 'commands/make.md'
        entry.unlink()
        entry.write_text('user replacement')
        before = installer.fingerprint(self.target)
        self.run_install('restore', ok=False)
        self.run_install(ok=False)
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_wrong_target_unsafe_ancestor_and_backup(self):
        self.run_install()
        self.run_install('restore', '--target-root', str(self.base / 'wrong'), ok=False)
        self.run_install('install', '--state-dir', str(self.target / 'backup'), ok=False)
        self.run_install('restore')
        outside = self.base / 'outside'
        outside.mkdir()
        (self.target / 'skills').symlink_to(outside)
        self.run_install(ok=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_symlink_and_copy_resource_resolution(self):
        for mode in ('symlink', 'copy'):
            with self.subTest(mode=mode):
                self.run_install('install', '--mode', mode)
                base = (self.target / 'skills/make').resolve().parents[3]
                self.assertTrue((base / 'scripts/read-planning-settings.py').is_file())
                p = subprocess.run(['bash', str(self.target / 'skills/exec/scripts/resolve-file.sh'),
                                    'agents/testing.txt'], cwd=self.base, env=self.env,
                                   text=True, capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, (self.source / 'plugins/planning/skills/exec/references/agents/testing.txt').read_text())
                self.assertEqual(base == self.source, mode == 'symlink')
                if mode == 'copy':
                    self.assertTrue((base / 'integrations/opencode/skill-eval/node_modules/@opencode/plugin/package.json').is_file())
                self.run_install('restore')

    def test_missing_source_or_sdk_and_corrupted_backup(self):
        sdk = self.source / 'integrations/opencode/skill-eval/node_modules/@opencode/plugin/package.json'
        sdk.unlink()
        self.run_install(ok=False)
        self.assertEqual(list(self.target.iterdir()), [])
        sdk.write_text('{"version":"2.1.1"}')
        inv = self.old()
        result = self.run_install('install', '--replace-inventory', str(inv))
        (Path(result['backup']) / 'skills/exec/SKILL.md').write_text('corrupt')
        before = installer.fingerprint(self.target)
        self.run_install('restore', ok=False)
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_missing_source_fails_before_any_changes(self):
        (self.source / 'commands/backlog.md').unlink()
        self.run_install(ok=False)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_mid_install_error_restores_old_entries(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        original = installer.rename_new
        def fail_one(src, dst):
            if dst == self.target / 'commands/backlog.md':
                raise OSError('controlled install failure')
            return original(src, dst)
        argv = ['install.py', 'install', '--source', str(self.source), '--target-root', str(self.target),
                '--state-dir', str(self.state), '--replace-inventory', str(inv)]
        with patch('sys.argv', argv), patch.object(installer, 'rename_new', fail_one):
            with self.assertRaisesRegex(OSError, 'controlled'):
                installer.main()
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_restore_without_source_manifest_and_legacy_state(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        self.run_install('install', '--replace-inventory', str(inv))
        statefile = self.state / 'installed.json'
        state = json.loads(statefile.read_text())
        state.pop('transaction')
        for item in state['entries'].values():
            for key in ('step', 'expected', 'desired', 'displaced'):
                item.pop(key, None)
        statefile.write_text(json.dumps(state))
        (self.source / 'install-manifest.json').write_text('corrupt manifest')
        (self.source / 'commands/backlog.md').unlink()
        self.run_install('restore')
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_copy_preparation_foreign_change_is_not_approved(self):
        inv = self.old()
        original = installer.clone
        def change_during_copy(src, dst):
            original(src, dst)
            if src == self.source / 'LICENSE':
                (self.target / 'skills/exec/late').write_text('unapproved work')
        argv = ['install.py', 'install', '--source', str(self.source), '--target-root', str(self.target),
                '--state-dir', str(self.state), '--replace-inventory', str(inv), '--mode', 'copy']
        with patch('sys.argv', argv), patch.object(installer, 'clone', change_during_copy):
            with self.assertRaisesRegex(ValueError, 'package preparation'):
                installer.main()
        self.assertEqual((self.target / 'skills/exec/late').read_text(), 'unapproved work')
        self.assertFalse((self.target / 'commands').exists())

    def test_arrival_during_rename_is_retained_not_overwritten(self):
        original = installer.rename_new
        def race(src, dst):
            if dst == self.target / 'skills/brainstorm':
                dst.write_text('arriving foreign entry')
            return original(src, dst)
        argv = ['install.py', 'install', '--source', str(self.source), '--target-root', str(self.target),
                '--state-dir', str(self.state)]
        with patch('sys.argv', argv), patch.object(installer, 'rename_new', race):
            with self.assertRaisesRegex(ValueError, 'foreign change'):
                installer.main()
        self.assertEqual((self.target / 'skills/brainstorm').read_text(), 'arriving foreign entry')

    def test_restore_copy_failure_can_be_retried(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        self.run_install('install', '--replace-inventory', str(inv))
        original = installer.clone
        def fail_backup(src, dst):
            if src.name == 'exec' and 'original' in src.parts:
                raise OSError('controlled restore copy failure')
            return original(src, dst)
        argv = ['install.py', 'restore', '--source', str(self.source), '--target-root', str(self.target),
                '--state-dir', str(self.state)]
        with patch('sys.argv', argv), patch.object(installer, 'clone', fail_backup):
            with self.assertRaisesRegex(OSError, 'controlled restore'):
                installer.main()
        self.run_install('restore')
        self.assertEqual(installer.fingerprint(self.target), before)

    def test_edit_during_displacement_is_preserved(self):
        inv = self.old()
        original = installer.rename_new
        entry = self.target / 'skills/exec'
        def change_before_rename(src, dst):
            if src == entry:
                (src / 'late').write_text('unapproved concurrent edit')
            return original(src, dst)
        argv = ['install.py', 'install', '--source', str(self.source), '--target-root', str(self.target),
                '--state-dir', str(self.state), '--replace-inventory', str(inv)]
        with patch('sys.argv', argv), patch.object(installer, 'rename_new', change_before_rename):
            with self.assertRaisesRegex(ValueError, 'foreign change'):
                installer.main()
        self.assertEqual((entry / 'late').read_text(), 'unapproved concurrent edit')
        self.assertEqual((entry / 'SKILL.md').read_text(), 'old actual installation\n')

    def test_killed_install_and_restore_are_recoverable(self):
        inv = self.old()
        before = installer.fingerprint(self.target)
        for action in ('install', 'restore'):
            if action == 'restore':
                self.run_install('install', '--replace-inventory', str(inv))
            code = '''import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('installer', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
original = m.rename_new
target = Path(sys.argv[2])
def kill_after_displace(src, dst):
    original(src, dst)
    if src == target / 'skills/exec':
        os._exit(99)
m.rename_new = kill_after_displace
sys.argv = ['install.py', sys.argv[3], '--source', sys.argv[4], '--target-root', str(target),
            '--state-dir', sys.argv[5], '--replace-inventory', sys.argv[6]]
m.main()
'''
            result = subprocess.run(['python3', '-c', code, str(ROOT / 'scripts/install.py'), str(self.target),
                                     action, str(self.source), str(self.state), str(inv)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 99, result.stderr)
            self.run_install('restore')
            self.assertEqual(installer.fingerprint(self.target), before)

    def test_target_lock_covers_different_state_directories(self):
        import fcntl
        key = installer.hashlib.sha256(os.fsencode(self.target.resolve())).hexdigest()[:16]
        with (self.target.parent / ('.cc-thingz-lock-' + key)).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            proc = subprocess.Popen(['python3', str(ROOT / 'scripts/install.py'), 'install', '--source', str(self.source),
                                     '--target-root', str(self.target), '--state-dir', str(self.base / 'other-state')],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    proc.wait(timeout=.2)
                self.assertEqual(list(self.target.iterdir()), [])
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                stdout, stderr = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, stderr)


if __name__ == '__main__':
    unittest.main()
