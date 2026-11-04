#!/usr/bin/env python3
"""Interactive snapshot-safe revdiff review; port of upstream git-review.py (MIT).

Auto: staged + unstaged + untracked, otherwise branch vs default. Explicit base
uses base...HEAD (or --branch target); explicit two/three-dot ranges are retained.
stdout is not a completion signal. Read --status and --output separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile


def git(*args, cwd=None):
    result = subprocess.run(['git', '--literal-pathspecs', *args], cwd=cwd, capture_output=True)
    if result.returncode:
        raise ValueError(f'git {args[0]} failed ({result.returncode}): {result.stderr.decode(errors="replace").strip()}')
    # No universal-newline conversion: source coordinates count LF, not CR/VT/NEL.
    return result.stdout.decode('utf-8').removesuffix('\n')


def git_ok(*args):
    return subprocess.run(['git', *args], capture_output=True).returncode == 0


def detect_default_branch():
    if git_ok('symbolic-ref', 'refs/remotes/origin/HEAD'):
        return git('symbolic-ref', 'refs/remotes/origin/HEAD').removeprefix('refs/remotes/')
    for prefix in ('origin/', ''):
        for branch in ('master', 'main', 'trunk'):
            if git_ok('rev-parse', '--verify', prefix + branch):
                return prefix + branch
    raise ValueError('cannot detect default branch; supply an explicit base ref')


def get_untracked_files():
    return [p for p in git('ls-files', '--others', '--exclude-standard', '-z').split('\0') if p]


def has_uncommitted_changes():
    return bool(git('diff', '--name-only') or git('diff', '--cached', '--name-only')
                or get_untracked_files())


def get_current_branch():
    if git_ok('symbolic-ref', '--quiet', 'HEAD'):
        return git('symbolic-ref', '--short', 'HEAD')
    return git('rev-parse', '--abbrev-ref', 'HEAD')


def get_project_name():
    if git_ok('remote', 'get-url', 'origin'):
        return git('remote', 'get-url', 'origin').rstrip('/').rsplit('/', 1)[-1].removesuffix('.git')
    return Path.cwd().name


def select_diff(base_ref=None, branch=None, staged=False, unstaged=False):
    if (base_ref or branch) and (staged or unstaged):
        raise ValueError('ref/branch cannot be combined with staged/unstaged')
    if branch and not base_ref:
        raise ValueError('--branch requires a base ref')
    if staged:
        return {'mode': 'staged', 'args': ['--cached'], 'branch': None}
    if unstaged:
        return {'mode': 'unstaged', 'args': [], 'branch': None}
    if base_ref:
        if base_ref.startswith('-') or (branch and branch.startswith('-')):
            raise ValueError('refs must not start with a dash')
        return {'mode': 'branch', 'args': [base_ref if '..' in base_ref else
                                         f'{base_ref}...{branch or "HEAD"}'], 'branch': branch}
    if not git_ok('rev-parse', '--verify', 'HEAD') or has_uncommitted_changes():
        base = 'HEAD' if git_ok('rev-parse', '--verify', 'HEAD') else git('hash-object', '-t', 'tree', os.devnull)
        return {'mode': 'uncommitted', 'args': [base], 'branch': None}
    return {'mode': 'branch', 'args': [f'{detect_default_branch()}...HEAD'], 'branch': None}


def get_file_status(diff_args):
    # NUL delimiters and disabled rename detection preserve arbitrary path names.
    fields = git('diff', '--no-color', '--no-renames', '--name-status', '-z', *diff_args, '--').split('\0')
    return {fields[i + 1]: {'A': 'new', 'M': 'modified', 'D': 'deleted'}.get(fields[i], 'changed')
            for i in range(0, len(fields) - 1, 2)}


def make_header(selection, file_count):
    branch = selection['branch'] or get_current_branch()
    parts = [f'Branch: {branch}', f'Mode: {selection["mode"]}']
    if selection['mode'] == 'uncommitted':
        for label, args in [('Staged', ['--cached']), ('Unstaged', [])]:
            parts.append(f'{label}: {len(get_file_status(args))}')
        parts.append(f'Untracked: {len(get_untracked_files())}')
    elif selection['mode'] == 'branch':
        span = selection['args'][0]
        base, target = re.split(r'\.{2,3}', span, maxsplit=1)
        # Upstream accepts explicit single refs as base...target and ranges as-is.
        base, target = base or 'HEAD', target or 'HEAD'
        parts.extend([f'Base: {base}', f'Commits: {git("rev-list", "--count", base + ".." + target)}'])
    parts.extend([f'Files: {file_count}', f'Diff: {selection["args"]!r}'])
    return ' | '.join(parts)


def build_snapshot(selection):
    args, mode = selection['args'], selection['mode']
    if mode != 'branch' and git('ls-files', '--unmerged', '-z'):
        raise ValueError('unresolved merge is not supported: resolve conflicts and git add the resolved paths, then regenerate review')
    statuses = get_file_status(args)
    lines, mapping, evidence = [], [], []

    def emit(text, location=None):
        lines.append(text)
        mapping.append(location)

    # Preserve upstream friendly headers and function context, but retain real
    # old/new line coordinates separately rather than guessing from display rows.
    emit('# ' + make_header(selection, len(statuses)))
    for name, status in statuses.items():
        # Blank context must retain its space prefix for the coordinate parser.
        raw = git('-c', 'diff.suppressBlankEmpty=false',
                  'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
                  '--word-diff=none', '--submodule=short', '--unified=3', *args, '--', name)
        # Binary display text alone does not identify either selected blob.
        binary_evidence = git('-c', 'diff.suppressBlankEmpty=false',
                              'diff', '--binary', '--full-index', '--no-ext-diff',
                               '--no-textconv', '--no-color', '--no-renames', '--submodule=short', *args, '--', name)
        evidence.append([name, raw, binary_evidence])
        emit('')
        emit(f'=== {json.dumps(name, ensure_ascii=False)} ({status}) ===', {'path': name, 'kind': 'file'})
        old = new = None
        submodule = False
        for line in raw.split('\n'):
            if line.startswith('diff --git '):
                # Type replacements have multiple sections for the same path.
                # Neither hunk coordinates nor entry modes cross that boundary.
                old = new = None
                submodule = False
                continue
            if old is None and re.match(r'^(?:index .* |(?:old|new|new file|deleted file) mode )160000$', line):
                submodule = True
            if line.startswith('@@@'):
                raise ValueError('combined merge diff is not supported: resolve conflicts and git add the resolved paths, then regenerate review')
            hunk = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)', line)
            if submodule and (hunk or line.startswith(('Submodule ', '+Subproject ', '-Subproject ', ' Subproject '))):
                emit(line, {'path': name, 'kind': 'metadata'})
            elif hunk:
                old, new = int(hunk[1]), int(hunk[2])
                emit('···' + hunk[3], {'path': name, 'kind': 'hunk', 'old': old, 'new': new})
            elif old is not None:
                kind = {'+': 'added', '-': 'deleted', ' ': 'context'}.get(line[:1], 'metadata')
                emit(line, {'path': name, 'kind': kind,
                            'old': old if kind in ('deleted', 'context') else None,
                            'new': new if kind in ('added', 'context') else None})
                old += kind in ('deleted', 'context')
                new += kind in ('added', 'context')
            elif line.startswith(('Binary files ', 'GIT binary patch', 'old mode ', 'new mode ')):
                emit(line, {'path': name, 'kind': 'metadata'})
            elif line.startswith('Submodule '):
                emit(line, {'path': name, 'kind': 'metadata'})
    if mode == 'uncommitted':
        trust_executable = git('config', '--type=bool', '--default=true', '--get', 'core.filemode') == 'true'
        for name in get_untracked_files():
            path = Path(name)
            symlink = path.is_symlink()
            # Git stores the link text, never the target's contents (or type).
            data = os.readlink(os.fsencode(path)) if symlink else path.read_bytes()
            # Match Git's new-entry mode, not unrelated filesystem permissions.
            git_mode = '120000' if symlink else (
                '100755' if trust_executable and path.stat().st_mode & 0o100 else '100644')
            evidence.append([name, git_mode, hashlib.sha256(data).hexdigest()])
            emit('')
            emit(f'=== {json.dumps(name, ensure_ascii=False)} (untracked) ===', {'path': name, 'kind': 'file'})
            try:
                text = data.decode('utf-8')
                if '\0' in text:
                    raise UnicodeError('binary')
                source_lines = text.removesuffix('\n').split('\n') if text else []
                for number, line in enumerate(source_lines, 1):
                    emit('+' + line, {'path': name, 'kind': 'added', 'old': None, 'new': number})
            except UnicodeError:
                emit('Binary untracked file (content not displayed)', {'path': name, 'kind': 'metadata'})
    # Include selected ref resolution and index state: identical net HEAD diff
    # after a staged/unstaged transition must still invalidate old annotations.
    refs = [git('rev-parse', '--verify', 'HEAD') if git_ok('rev-parse', '--verify', 'HEAD')
            else 'unborn:' + git('symbolic-ref', 'HEAD')]
    if mode == 'branch':
        refs.append(git('rev-parse', *args))
    if mode in ('uncommitted', 'staged'):
        refs.append(git('ls-files', '--stage', '-z'))
    content = '\n'.join(lines) + '\n' if evidence else ''
    digest = hashlib.sha256(json.dumps([selection, refs, evidence, content], ensure_ascii=False).encode()).hexdigest()
    return {'snapshot_text': content, 'line_map': mapping if evidence else [],
            'review_sha256': digest, 'selection': selection}


def verify_status(status):
    os.chdir(status['repository'])
    if build_snapshot(status['selection'])['review_sha256'] != status['review_sha256']:
        raise ValueError('stale snapshot: regenerate review before applying annotations')


def launch(argv):
    """Forward cancellation so the shared launcher can clean up its worker."""
    child = subprocess.Popen(argv)
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    previous = {sig: signal.signal(sig, interrupt)
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run_review(args, terminal_args):
    output, status = Path(args.output).absolute(), Path(args.status).absolute()
    # Fresh caller-owned files, same fail-closed contract as Task 5.
    with status.open('x'):
        pass
    with output.open('x'):
        pass
    result = {'state': 'failed', 'annotations': str(output)}
    rc = 1
    try:
        root = git('rev-parse', '--show-toplevel')
        os.chdir(root)
        result['repository'] = root
        selection = select_diff(args.base_ref, args.branch, args.staged, args.unstaged)
        snapshot = build_snapshot(selection)
        result.update(snapshot)
        if os.environ.get('PLANNING_DISABLE_REVDIFF'):
            result.update(state='skipped', reason='PLANNING_DISABLE_REVDIFF')
            return 0
        if not snapshot['snapshot_text']:
            result.update(state='no-changes', reason='no changes in selected diff; not review approval')
            return 0
        # Only terminal/status operations are shared. The cleaned code diff is
        # compared against empty by the existing immutable-file launcher; this
        # keeps friendly context and lets revdiff rows map exactly to line_map.
        launcher = Path(__file__).resolve().parents[4] / 'planning/scripts/plan-review-launcher.py'
        with tempfile.TemporaryDirectory(prefix='git-review-', dir='/tmp/opencode') as directory:
            run = Path(directory)
            review = run / 'review.diff'
            review.write_text(snapshot['snapshot_text'])
            code = launch([sys.executable, str(launcher), str(review),
                           '--output', str(run / 'annotations'), '--status', str(run / 'status'),
                           '--exit-code-on-annotations', *terminal_args])
            handoff = json.loads((run / 'status').read_text())
            result['launcher'] = handoff
            result['annotation_file'] = 'review.diff'
            result['state'] = handoff['state']
            if code or handoff['state'] not in ('annotations', 'needs-confirmation', 'skipped'):
                result['reason'] = handoff.get('reason', 'launcher failed')
                return code or 1
            try:
                verify_status(result)
            except ValueError:
                result['state'] = 'stale'
                raise
            output.write_bytes((run / 'annotations').read_bytes())
            rc = 0
    except KeyboardInterrupt:
        result.update(state='cancelled', reason='interrupted; not approved')
        rc = 130
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result['reason'] = str(exc)
        print(f'error: {exc}', file=sys.stderr)
    finally:
        status.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return rc


def run_tests():
    """Useful upstream self-tests retained; editor/tracking-repo tests retired."""
    import unittest

    class OriginalContracts(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.directory = tempfile.TemporaryDirectory(prefix='git-review-self-test-', dir='/tmp/opencode')
            cls.cwd = Path.cwd()
            os.chdir(cls.directory.name)
            git('init', '-q', '-b', 'main')
            git('-c', 'user.email=review@local', '-c', 'user.name=review',
                'commit', '--allow-empty', '-qm', 'initial')

        @classmethod
        def tearDownClass(cls):
            os.chdir(cls.cwd)
            cls.directory.cleanup()

        def test_default_branch(self):
            self.assertTrue(detect_default_branch())

        def test_project_name(self):
            self.assertTrue(get_project_name())

        def test_current_branch(self):
            self.assertIsInstance(get_current_branch(), str)

        def test_uncommitted(self):
            self.assertIsInstance(has_uncommitted_changes(), bool)

        def test_untracked(self):
            self.assertIsInstance(get_untracked_files(), list)

        def test_empty_diff(self):
            self.assertEqual(get_file_status(['HEAD']), {})

        def test_empty_clean_diff(self):
            self.assertEqual(build_snapshot(select_diff())['snapshot_text'], '')

        def test_uncommitted_header(self):
            header = make_header({'mode': 'uncommitted', 'args': ['HEAD'], 'branch': None}, 0)
            self.assertIn('Branch:', header)
            self.assertIn('Staged:', header)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OriginalContracts)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_ref', nargs='?')
    parser.add_argument('--branch')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--staged', action='store_true')
    group.add_argument('--unstaged', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--status')
    parser.add_argument('--check-status', help='verify snapshot immediately before applying/confirming')
    parser.add_argument('--test', action='store_true')
    # Same public terminal contract, delegated unchanged to the Task 5 launcher.
    terminal_flags = ('terminal', 'backend', 'tmux-socket', 'tmux-client', 'tmux-pane',
                      'kitty-socket', 'kitty-window-id', 'wayland-display', 'display',
                      'xdg-runtime-dir', 'timeout')
    for flag in terminal_flags:
        parser.add_argument('--' + flag)
    args = parser.parse_args()
    terminal_args = []
    for flag in terminal_flags:
        value = getattr(args, flag.replace('-', '_'))
        if value is not None:
            terminal_args.extend(['--' + flag, value])
    if args.test:
        return run_tests()
    if args.check_status:
        if terminal_args:
            parser.error('unexpected arguments with --check-status')
        verify_status(json.loads(Path(args.check_status).read_text()))
        return 0
    if not args.output or not args.status:
        parser.error('--output and --status required; terminal flags follow the Task 5 launcher contract')
    return run_review(args, terminal_args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        sys.exit(1)
