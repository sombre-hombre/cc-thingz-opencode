"""Real Git selection/mapping and subprocess handoff, not human UI acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'plugins/review/skills/git-review/scripts/git-review.py'
spec = importlib.util.spec_from_file_location('review', SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

TERMINAL = '''#!/usr/bin/env python3
import json, subprocess, sys
a = sys.argv[1:]
if a[0] == '-S':
    assert a[:2] == ['-S', '/chosen socket']
    if a[2] == 'list-clients':
        print('/chosen client\\t$1')
        sys.exit(0)
    if a[2] == 'display-message':
        print('%3\\t$1')
        sys.exit(0)
    assert a[a.index('-c') + 1] == '/chosen client'
    assert a[a.index('-t') + 1] == '%3'
    sys.exit(subprocess.call(a[-1], shell=True))
if a[0] == '@':
    assert a[:3] == ['@', '--to', 'unix:/chosen kitty']
    if a[3] == 'ls':
        print(json.dumps([{'tabs': [{'windows': [{'id': 42}]}]}]))
        sys.exit(0)
    if a[3] == 'close-window':
        assert a[-1] == 'id:123'
        sys.exit(0)
    assert a[a.index('--source-window') + 1] == 'id:42'
    subprocess.Popen(a[a.index('--') + 1:], start_new_session=True)
    print(123)
    sys.exit(0)
sys.exit(subprocess.call(a[a.index('--') + 1:]))
'''

REVDIFF = '''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
a = sys.argv[1:]
text = Path(a[a.index('--compare-new') + 1]).read_text()
assert not Path(a[a.index('--compare-old') + 1]).read_bytes()
assert '=== ' in text
mode = os.environ.get('MODE', 'annotations')
if mode == 'block':
    Path(os.environ['READY']).write_text(str(os.getpid()))
    time.sleep(30)
if mode == 'stale':
    Path(os.environ['SOURCE']).write_text('changed during review\\n')
if mode in ('annotations', 'stale', 'failure'):
    row = next(i for i, line in enumerate(text.splitlines(), 1) if line.startswith('+'))
    Path(a[a.index('--output') + 1]).write_text(f'## review.diff:{row} (+)\\n\\nValidate this line\\n')
    sys.exit(7 if mode == 'failure' else 10)
'''


class GitReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="git-review-test ' ", dir='/tmp/opencode')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.repo = self.run / 'repo with spaces'
        self.repo.mkdir()
        self.oldcwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.oldcwd)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'test@local')
        self.git('config', 'user.name', 'test')
        self.source = self.repo / "a ' file.txt"
        self.source.write_text('one\ntwo\nthree\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial')
        self.bin = self.run / 'bin'
        self.bin.mkdir()
        for name, text in [('kitty', TERMINAL), ('foot', TERMINAL), ('tmux', TERMINAL), ('revdiff', REVDIFF)]:
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'], WAYLAND_DISPLAY='test',
                        XDG_RUNTIME_DIR=str(self.run), SOURCE=str(self.source), READY=str(self.run / 'ready'),
                        TMUX='stale', KITTY_WINDOW_ID='wrong')
        self.env.pop('PLANNING_DISABLE_REVDIFF', None)
        self.counter = 0

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True).strip()

    def modify(self):
        self.source.write_text('one\nstaged\nthree\n')
        self.git('add', '.')
        self.source.write_text('one\nstaged\nunstaged\n')

    def invoke(self, *selection, mode='annotations', backend='kitty-window', extra_env=None):
        self.counter += 1
        output, status = self.run / f'out{self.counter}', self.run / f'status{self.counter}'
        argv = [sys.executable, str(SCRIPT), *selection, '--output', str(output), '--status', str(status),
                '--terminal', backend, '--timeout', '3']
        if backend == 'tmux':
            argv += ['--tmux-socket', '/chosen socket', '--tmux-client', '/chosen client', '--tmux-pane', '%3']
        if backend == 'kitty-overlay':
            argv += ['--kitty-socket', 'unix:/chosen kitty', '--kitty-window-id', '42']
        result = subprocess.run(argv, env=dict(self.env, MODE=mode, **(extra_env or {})), capture_output=True, timeout=15)
        self.assertEqual(result.stdout, b'')
        return result, json.loads(status.read_text()), output.read_text(), status

    def test_auto_staged_unstaged_untracked_and_mapping(self):
        self.modify()
        (self.repo / 'new\tfile\n.txt').write_text('untracked\n')
        result, status, annotations, _ = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(status['state'], 'annotations')
        self.assertEqual(status['launcher']['revdiff_exit'], 10)
        self.assertIn('+staged', status['snapshot_text'])
        self.assertIn('+unstaged', status['snapshot_text'])
        self.assertIn('+untracked', status['snapshot_text'])
        row = int(annotations.split(':')[1].split()[0])
        self.assertEqual(status['line_map'][row - 1], {'path': self.source.name, 'kind': 'added', 'old': None, 'new': 2})
        deleted = next(m for m in status['line_map'] if m and m.get('kind') == 'deleted')
        self.assertEqual((deleted['old'], deleted['new']), (2, None))
        review.verify_status(status)

    def test_staged_and_unstaged_are_distinct(self):
        self.modify()
        for flag, yes, no in [('--staged', '+staged', '+unstaged'), ('--unstaged', '+unstaged', '+staged')]:
            result, status, _, _ = self.invoke(flag)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(yes, status['snapshot_text'])
            self.assertNotIn(no, status['snapshot_text'])

    def test_unresolved_merge_refuses_without_mutating_repository(self):
        self.git('checkout', '-qb', 'other')
        self.source.write_text('other\n')
        self.git('commit', '-qam', 'other')
        self.git('checkout', '-q', 'main')
        self.source.write_text('main\n')
        self.git('commit', '-qam', 'main')
        merged = subprocess.run(['git', 'merge', 'other'], capture_output=True)
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn('@@@', self.git('diff'))
        before = (self.source.read_bytes(), (self.repo / '.git/index').read_bytes(), self.git('status', '--porcelain'))
        for selection in ((), ('--unstaged',), ('--staged',)):
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(ValueError, 'unresolved merge.*resolve conflicts.*git add'):
                    review.build_snapshot(review.select_diff(staged='--staged' in selection,
                                                           unstaged='--unstaged' in selection))
                result, status, output, _ = self.invoke(*selection, mode='empty')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(status['state'], 'failed')
                self.assertIn('resolve conflicts', status['reason'])
                self.assertNotIn('launcher', status)
                self.assertEqual(output, '')
                self.assertEqual((self.source.read_bytes(), (self.repo / '.git/index').read_bytes(),
                                  self.git('status', '--porcelain')), before)
        # Explicit committed comparisons remain reviewable despite the index.
        snapshot = review.build_snapshot(review.select_diff('other..main'))
        review.verify_status(dict(snapshot, repository=str(self.repo)))
        self.source.write_text('resolved\n')
        self.git('add', '--', self.source.name)
        result, status, _, _ = self.invoke('--staged')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+resolved', status['snapshot_text'])
        review.verify_status(status)

    def test_file_type_replacement_sections_preserve_deleted_license_and_coordinates(self):
        license_text = (ROOT / 'LICENSE').read_text()
        license_path = self.repo / 'LICENSE'
        license_path.write_text(license_text)
        self.git('add', 'LICENSE')
        self.git('commit', '-qm', 'license')
        base = self.git('rev-parse', 'HEAD')
        license_path.unlink()
        for replacement in ('gitlink', 'symlink'):
            with self.subTest(replacement=replacement):
                self.git('update-index', '--force-remove', 'LICENSE')
                if replacement == 'gitlink':
                    self.git('update-index', '--add', '--cacheinfo', '160000', base, 'LICENSE')
                else:
                    license_path.symlink_to('replacement-target')
                    self.git('add', 'LICENSE')
                raw = self.git('diff', '--cached', '--', 'LICENSE')
                self.assertEqual(raw.count('diff --git '), 2)
                snapshot = review.build_snapshot(review.select_diff(staged=True))
                rows = list(zip(snapshot['snapshot_text'].split('\n'), snapshot['line_map']))
                deleted = [(text, loc) for text, loc in rows if loc and loc['kind'] == 'deleted']
                self.assertEqual([text for text, _ in deleted], ['-' + line for line in license_text.splitlines()])
                self.assertEqual([loc['old'] for _, loc in deleted], list(range(1, len(license_text.splitlines()) + 1)))
                self.assertTrue(all(loc['new'] is None for _, loc in deleted))
                self.assertFalse(any(text.startswith(('--- ', '+++ ')) and loc and
                                     loc['kind'] in ('added', 'deleted', 'context') for text, loc in rows))
                if replacement == 'gitlink':
                    pointer = [(text, loc) for text, loc in rows if text.startswith('+Subproject commit')]
                    self.assertEqual(pointer, [('+Subproject commit ' + base, {'path': 'LICENSE', 'kind': 'metadata'})])
                else:
                    added = [(text, loc) for text, loc in rows if loc and loc['kind'] == 'added']
                    self.assertEqual(added, [('+replacement-target', {'path': 'LICENSE', 'kind': 'added', 'old': None, 'new': 1})])
                review.verify_status(dict(snapshot, repository=str(self.repo)))
                # Changing selected content still invalidates the verified mapping.
                self.git('update-index', '--force-remove', 'LICENSE')
                with self.assertRaisesRegex(ValueError, 'stale snapshot'):
                    review.verify_status(dict(snapshot, repository=str(self.repo)))

    def test_submodule_diff_and_log_config_cannot_map_nested_source_to_directory(self):
        self.git('init', '-q', 'vendor')
        nested = self.repo / 'vendor/foreign.txt'
        nested.write_text('first\n')
        self.git('-C', 'vendor', 'add', '.')
        self.git('-C', 'vendor', '-c', 'user.name=test', '-c', 'user.email=test@local',
                 'commit', '-qm', 'first')
        first = self.git('-C', 'vendor', 'rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', '160000', first, 'vendor')
        self.git('commit', '-qm', 'gitlink')
        nested.write_text('foreign.txt\n')
        self.git('-C', 'vendor', 'add', '.')
        self.git('-C', 'vendor', '-c', 'user.name=test', '-c', 'user.email=test@local',
                 'commit', '-qm', 'second')
        second = self.git('-C', 'vendor', 'rev-parse', 'HEAD')
        selection = review.select_diff(unstaged=True)
        baseline = review.build_snapshot(selection)
        status = dict(baseline, repository=str(self.repo))
        for setting in ('diff', 'log'):
            with self.subTest(setting=setting):
                self.git('config', 'diff.submodule', setting)
                config = (self.repo / '.git/config').read_bytes()
                index = (self.repo / '.git/index').read_bytes()
                raw = self.git('diff')
                if setting == 'diff':
                    self.assertIn('+foreign.txt', raw)
                    self.assertIn('@@ -1 +1 @@', raw)
                else:
                    self.assertIn('> second', raw)
                snapshot = review.build_snapshot(selection)
                self.assertEqual(snapshot, baseline)  # display AND evidence deterministic
                rows = list(zip(snapshot['snapshot_text'].split('\n'), snapshot['line_map']))
                self.assertNotIn('+foreign.txt', snapshot['snapshot_text'])
                self.assertEqual([(text, loc) for text, loc in rows if 'Subproject commit' in text],
                                 [('-Subproject commit ' + first, {'path': 'vendor', 'kind': 'metadata'}),
                                  ('+Subproject commit ' + second, {'path': 'vendor', 'kind': 'metadata'})])
                self.assertFalse(any(loc and loc['path'] == 'vendor' and
                                     ('old' in loc or 'new' in loc) for _, loc in rows))
                status = dict(snapshot, repository=str(self.repo))
                review.verify_status(status)
                self.assertEqual((self.repo / '.git/config').read_bytes(), config)
                self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        # The selected pointer, not nested source coordinates, guards staleness.
        self.git('-C', 'vendor', 'checkout', '-q', first)
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(status)

    def test_submodule_pointer_rows_are_file_metadata_not_source_coordinates(self):
        # Real gitlink entries and a checkout, without network/submodule add.
        self.git('init', '-q', 'vendor')
        self.git('-C', 'vendor', '-c', 'user.name=test', '-c', 'user.email=test@local',
                 'commit', '--allow-empty', '-qm', 'first')
        first = self.git('-C', 'vendor', 'rev-parse', 'HEAD')
        self.git('update-index', '--add', '--cacheinfo', '160000', first, 'vendor')
        self.git('commit', '-qm', 'gitlink')
        self.git('-C', 'vendor', '-c', 'user.name=test', '-c', 'user.email=test@local',
                 'commit', '--allow-empty', '-qm', 'second')
        before = (self.repo / '.git/index').read_bytes()
        self.assertIn('+Subproject commit', self.git('diff'))
        result, status, _, _ = self.invoke('--unstaged')
        self.assertEqual(result.returncode, 0, result.stderr)
        pointer_rows = [(text, loc) for text, loc in zip(status['snapshot_text'].split('\n'), status['line_map'])
                        if 'Subproject commit' in text]
        self.assertEqual(len(pointer_rows), 2)
        self.assertTrue(all(loc == {'path': 'vendor', 'kind': 'metadata'} for _, loc in pointer_rows))
        review.verify_status(status)
        self.assertEqual((self.repo / '.git/index').read_bytes(), before)
        self.git('add', 'vendor')
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(status)
        # A normal source file with the same text still has real coordinates.
        self.source.write_text('Subproject commit ordinary source\n')
        snapshot = review.build_snapshot(review.select_diff(unstaged=True))
        self.assertIn({'path': self.source.name, 'kind': 'added', 'old': None, 'new': 1}, snapshot['line_map'])

    def test_unborn_staged_untracked_and_net_worktree_review(self):
        self.repo = self.run / 'unborn'
        self.repo.mkdir()
        os.chdir(self.repo)
        self.git('init', '-q', '-b', 'main')
        self.source = self.repo / 'first.txt'
        result, empty, _, _ = self.invoke('--staged', mode='empty')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(empty['state'], 'no-changes')
        review.verify_status(empty)
        self.source.write_text('staged\n')
        result, untracked, _, _ = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+staged', untracked['snapshot_text'])
        review.verify_status(untracked)
        self.git('add', '.')
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(untracked)
        self.source.write_text('net worktree\n')
        (self.repo / 'untracked').write_text('new file\n')
        before = ((self.repo / '.git/index').read_bytes(), self.source.read_bytes(), self.git('status', '--porcelain'))
        for selection, yes, no in [(('--staged',), '+staged', '+net worktree'),
                                    ((), '+net worktree', '+staged'),
                                    (('--unstaged',), '+net worktree', '+new file')]:
            result, status, _, _ = self.invoke(*selection)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Branch: main', status['snapshot_text'])
            self.assertIn(yes, status['snapshot_text'])
            self.assertNotIn(no, status['snapshot_text'])
            if not selection:
                self.assertIn('+new file', status['snapshot_text'])
            review.verify_status(status)
            self.assertEqual(((self.repo / '.git/index').read_bytes(), self.source.read_bytes(),
                              self.git('status', '--porcelain')), before)
        result, status, _, _ = self.invoke('missing-ref', mode='empty')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')
        result, status, _, _ = self.invoke('--staged')
        self.git('-c', 'user.name=test', '-c', 'user.email=test@local', 'commit', '-qm', 'first')
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(status)

    def test_untracked_symlinks_use_exact_git_link_text_without_target_exposure(self):
        secret = self.run / 'private target'
        secret.write_text('PRIVATE TARGET MUST NOT APPEAR\n')
        directory = self.run / 'target directory'
        directory.mkdir()
        links = {'file link': secret, 'directory link': directory,
                 'dangling link': self.run / 'missing target'}
        for name, target in links.items():
            (self.repo / name).symlink_to(target)
        result, status, _, _ = self.invoke(mode='empty')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(status['state'], 'needs-confirmation')
        self.assertNotIn('PRIVATE TARGET MUST NOT APPEAR', status['snapshot_text'])
        review.verify_status(status)
        secret.write_text('CHANGED PRIVATE CONTENT\n')
        review.verify_status(status)  # target bytes are not part of Git's link blob
        secret.chmod(0o755)
        review.verify_status(status)  # target permissions do not change Git's 120000 mode
        for name in links:
            link = self.repo / name
            self.git('add', '--', name)
            blob = subprocess.check_output(['git', 'show', ':' + name])
            self.assertEqual(blob, os.readlink(os.fsencode(link)))
            rows = [line[1:] for line, location in
                    zip(status['snapshot_text'].split('\n'), status['line_map'])
                    if location and location.get('path') == name and location['kind'] == 'added']
            self.assertEqual('\n'.join(rows).encode(), blob)
        # Build another untracked snapshot, then change only the link text.
        self.git('reset', '-q')
        snapshot = review.build_snapshot(review.select_diff())
        link = self.repo / 'dangling link'
        link.unlink()
        link.symlink_to(self.run / 'different missing target')
        with self.assertRaisesRegex(ValueError, 'stale'):
            review.verify_status(dict(snapshot, repository=str(self.repo)))

    def test_untracked_executable_change_invalidates_check_status(self):
        self.git('config', 'core.filemode', 'true')
        path = self.repo / 'new.sh'
        path.write_bytes(b'echo same content\n')
        for before, after, git_mode in [(0o644, 0o755, '100755'), (0o755, 0o644, '100644')]:
            with self.subTest(before=oct(before), after=oct(after)):
                path.chmod(before)
                result, status, _, evidence = self.invoke(mode='empty')
                self.assertEqual(result.returncode, 0, result.stderr)
                review.verify_status(status)
                data = path.read_bytes()
                path.chmod(after)
                self.assertEqual(path.read_bytes(), data)
                checked = subprocess.run([sys.executable, str(SCRIPT), '--check-status', str(evidence)],
                                         capture_output=True)
                self.assertNotEqual(checked.returncode, 0)
                self.assertIn(b'stale snapshot', checked.stderr)
                self.git('add', '--', path.name)
                self.assertEqual(self.git('ls-files', '--stage', '--', path.name).split()[0], git_mode)
                self.git('reset', '-q', '--', path.name)

    def test_untracked_mode_matches_git_not_all_filesystem_permissions(self):
        path = self.repo / 'new.sh'
        path.write_text('same content\n')
        for filemode, before, after, git_mode in [('true', 0o644, 0o654, '100644'),
                                                 ('false', 0o644, 0o755, '100644')]:
            with self.subTest(filemode=filemode):
                self.git('config', 'core.filemode', filemode)
                path.chmod(before)
                snapshot = review.build_snapshot(review.select_diff())
                path.chmod(after)
                review.verify_status(dict(snapshot, repository=str(self.repo)))
                self.git('add', '--', path.name)
                self.assertEqual(self.git('ls-files', '--stage', '--', path.name).split()[0], git_mode)
                self.git('reset', '-q', '--', path.name)

    def test_tracked_mode_evidence_respects_selected_diff(self):
        self.git('config', 'core.filemode', 'true')
        self.source.chmod(0o644)
        self.source.write_text('selected change\n')
        staged = review.build_snapshot(review.select_diff(staged=True))
        unstaged = review.build_snapshot(review.select_diff(unstaged=True))
        branch = review.build_snapshot(review.select_diff('HEAD'))
        self.source.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(dict(unstaged, repository=str(self.repo)))
        for snapshot in (staged, branch):
            review.verify_status(dict(snapshot, repository=str(self.repo)))
        self.git('add', '--', self.source.name)
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(dict(staged, repository=str(self.repo)))

    def test_branch_refs_ranges_no_checkout_and_context(self):
        self.git('checkout', '-qb', 'feature')
        self.source.write_text('one\ncommitted\nthree\n')
        self.git('commit', '-qam', 'feature')
        self.git('checkout', '-q', 'main')
        self.source.write_text('dirty ignored by ref review\n')
        for selection in [('main', '--branch', 'feature'), ('main..feature',), ('main...feature',)]:
            result, status, _, _ = self.invoke(*selection)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('+committed', status['snapshot_text'])
            self.assertIn(' one', status['snapshot_text'])
            self.assertNotIn('dirty ignored', status['snapshot_text'])
            self.assertEqual(self.git('branch', '--show-current'), 'main')

    def test_auto_clean_branch_and_empty(self):
        result, status, _, _ = self.invoke()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'no-changes')
        self.git('checkout', '-qb', 'feature')
        self.source.write_text('committed\n')
        self.git('commit', '-qam', 'feature')
        result, status, _, _ = self.invoke(mode='empty')
        self.assertEqual(status['state'], 'needs-confirmation')
        self.assertEqual(status['selection']['mode'], 'branch')

    def test_remote_default_without_local_base(self):
        initial = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', initial)
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.git('checkout', '-qb', 'feature')
        self.git('branch', '-D', 'main')
        self.source.write_text('remote comparison\n')
        self.git('commit', '-qam', 'feature')
        result, status, _, _ = self.invoke(mode='empty')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(status['selection']['args'], ['origin/main...HEAD'])
        self.assertIn('Base: origin/main', status['snapshot_text'])

    def test_all_terminal_backends_empty_not_clean(self):
        self.modify()
        for backend in ('kitty-window', 'foot-window', 'kitty-overlay', 'tmux'):
            result, status, output, _ = self.invoke(mode='empty', backend=backend)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(status['state'], 'needs-confirmation')
            self.assertEqual(output, '')

    def test_stale_during_and_after_review(self):
        self.modify()
        result, status, output, _ = self.invoke(mode='stale')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'stale')
        self.assertEqual(output, '')
        result, status, _, path = self.invoke()
        self.git('add', '.')  # same HEAD diff, different staged selection evidence
        checked = subprocess.run([sys.executable, str(SCRIPT), '--check-status', str(path)], capture_output=True)
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn(b'stale', checked.stderr)

    def test_ref_moves_invalidate_snapshot(self):
        self.modify()
        self.git('commit', '-qam', 'change')
        result, status, _, _ = self.invoke('HEAD~1', mode='empty')
        self.assertEqual(result.returncode, 0)
        self.git('commit', '--allow-empty', '-qm', 'advance')
        with self.assertRaisesRegex(ValueError, 'stale'):
            review.verify_status(status)

    def test_git_and_revdiff_errors_disable_and_timeout(self):
        self.modify()
        for selection, mode, state in [(('missing-ref',), 'empty', 'failed'), ((), 'failure', 'failed'), ((), 'block', 'cancelled')]:
            result, status, output, _ = self.invoke(*selection, mode=mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(status['state'], state)
            self.assertEqual(output, '')
        result, status, _, _ = self.invoke(extra_env={'PLANNING_DISABLE_REVDIFF': '0'})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'skipped')

    def test_binary_untracked_and_literal_pathspec(self):
        (self.repo / ':(glob)*').write_text('literal name\n')
        (self.repo / 'binary').write_bytes(b'\x00\xff')
        result, status, _, _ = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Binary untracked', status['snapshot_text'])
        self.assertIn('literal name', status['snapshot_text'])
        self.git('add', '.')
        result, status, _, _ = self.invoke('--staged')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('literal name', status['snapshot_text'])

    def test_blank_context_mapping_ignores_suppress_blank_empty_config(self):
        before = 'one\n\nanchor\nold\n\nafter\n'
        after = 'one\n\nanchor\nnew\n\nafter\n'
        self.source.write_text(before)
        self.git('commit', '-qam', 'blank context base')
        self.source.write_text(after)
        for setting in ('true', 'false'):
            with self.subTest(suppressBlankEmpty=setting):
                self.git('config', 'diff.suppressBlankEmpty', setting)
                config = (self.repo / '.git/config').read_bytes()
                result, status, annotations, evidence = self.invoke('--unstaged')
                self.assertEqual(result.returncode, 0, result.stderr)
                row = int(annotations.split(':')[1].split()[0])
                self.assertEqual(status['line_map'][row - 1],
                                 {'path': self.source.name, 'kind': 'added', 'old': None, 'new': 4})
                blank_context = []
                for text, location in zip(status['snapshot_text'].split('\n'), status['line_map']):
                    if not location or location['kind'] not in ('added', 'deleted', 'context'):
                        continue
                    for side, source in [('old', before), ('new', after)]:
                        number = location[side]
                        if number is not None:
                            self.assertEqual(text[1:], source.split('\n')[number - 1])
                    if text == ' ':
                        blank_context.append((location['kind'], location['old'], location['new']))
                self.assertEqual(blank_context, [('context', 2, 2), ('context', 5, 5)])
                review.verify_status(status)
                self.source.write_text(after + 'later\n')
                checked = subprocess.run([sys.executable, str(SCRIPT), '--check-status', str(evidence)],
                                         capture_output=True)
                self.assertNotEqual(checked.returncode, 0)
                self.assertIn(b'stale snapshot', checked.stderr)
                self.source.write_text(after)
                self.assertEqual((self.repo / '.git/config').read_bytes(), config)

    def test_line_mapping_counts_lf_not_unicode_separators(self):
        self.source.write_bytes(b'one\nembedded\vvertical\rcarriage\nlast\n')
        snapshot = review.build_snapshot(review.select_diff())
        added = [m for m in snapshot['line_map'] if m and m.get('kind') == 'added']
        self.assertEqual([m['new'] for m in added], [2, 3])
        self.assertEqual(len(snapshot['line_map']), snapshot['snapshot_text'].count('\n'))
        (self.repo / 'new.txt').write_text('vertical\vtab\nnext\n')
        snapshot = review.build_snapshot(review.select_diff())
        added = [m for m in snapshot['line_map'] if m and m.get('path') == 'new.txt' and m.get('kind') == 'added']
        self.assertEqual([m['new'] for m in added], [1, 2])

    def test_fresh_handoff_no_overwrite(self):
        self.modify()
        output, status = self.run / 'existing', self.run / 'status'
        output.write_text('preserve')
        result = subprocess.run([sys.executable, str(SCRIPT), '--output', str(output), '--status', str(status)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_text(), 'preserve')

    def test_tracked_binary_edit_invalidates_unstaged_review(self):
        binary = self.repo / 'tracked.bin'
        binary.write_bytes(b'\x00base')
        self.git('add', 'tracked.bin')
        self.git('commit', '-qm', 'binary base')
        binary.write_bytes(b'\x00first')
        result, status, _, _ = self.invoke('--unstaged', mode='empty')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Binary files', status['snapshot_text'])
        review.verify_status(status)
        binary.write_bytes(b'\x00other')
        with self.assertRaisesRegex(ValueError, 'stale snapshot'):
            review.verify_status(status)
        evidence = self.repo / 'old-status.json'
        evidence.write_text(json.dumps(status))
        checked = subprocess.run(['python3', str(ROOT / 'plugins/review/skills/git-review/scripts/git-review.py'),
                                  '--check-status', str(evidence)], cwd=self.repo, capture_output=True, text=True)
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn('stale snapshot', checked.stderr)

    def test_missing_revdiff_and_outside_repository(self):
        self.modify()
        (self.bin / 'revdiff').unlink()
        # Restricted PATH still has git, but cannot discover system revdiff.
        (self.bin / 'git').symlink_to(shutil.which('git'))
        result, status, output, _ = self.invoke(extra_env={'PATH': str(self.bin)})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')
        self.assertIn('missing dependency: revdiff', status['reason'])
        self.assertEqual(output, '')
        os.chdir(self.run)
        result, status, output, _ = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(status['state'], 'failed')
        self.assertIn('git rev-parse failed', status['reason'])

    def test_signal_cancel_propagates_and_cleans_worker(self):
        self.modify()
        output, status = self.run / 'out', self.run / 'status'
        child = subprocess.Popen([sys.executable, str(SCRIPT), '--output', str(output), '--status', str(status),
                                  '--terminal', 'kitty-window', '--timeout', '30'], env=dict(self.env, MODE='block'),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ready = self.run / 'ready'
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        try:
            self.assertTrue(ready.exists())
            pid = int(ready.read_text())
            child.send_signal(signal.SIGTERM)
            out, err = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 130, err)
            self.assertEqual(out, b'')
            self.assertEqual(json.loads(status.read_text())['state'], 'cancelled')
            self.assertEqual(output.read_text(), '')
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
