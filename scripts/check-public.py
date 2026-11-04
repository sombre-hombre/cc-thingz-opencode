#!/usr/bin/env python3
"""Offline, heuristic publication checks. Findings never print secret values.

Scans tracked/unignored export files, then all reachable Git blobs and commit
identities. This complements, rather than replaces, a dedicated secret scanner.
"""
import argparse
import re
import subprocess
from pathlib import Path

PATTERNS = {
    'personal home directory': re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
    'real session identifier': re.compile(rb'\bses_[a-f0-9]{16,}[A-Za-z0-9]*\b'),
    'private key': re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'),
    'GitHub credential': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'GitLab credential': re.compile(rb'\bglpat-[A-Za-z0-9_-]{20,}\b'),
    'OpenAI credential': re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b'),
    'AWS access key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'URL with password': re.compile(rb'https?://[^\s/:@]+:[^\s/@]{5,}@'),
}
AUTHOR = 'sombre-hombre <324544+sombre-hombre@users.noreply.github.com>'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def inspect(data, label, errors):
    for name, pattern in PATTERNS.items():
        if pattern.search(data):
            errors.append(f'{label}: {name}')


def audit(root, history=True, expected_author=None):
    errors = []
    names = set(git(root, 'ls-files', '-co', '--exclude-standard', '-z').decode().split('\0')) - {''}
    for name in sorted(names):
        path = root / name
        if path.is_symlink():
            errors.append(f'{name}: publication symlinks must be reviewed explicitly')
        elif path.is_file():
            inspect(path.read_bytes(), name, errors)
        if name.startswith(('docs/plans/', 'tests/smoke/evidence/', 'local-reports/', 'local-evidence/')) or name in ('docs/run-stats.json', 'docs/run-decisions.md'):
            errors.append(f'{name}: local run artifact')
        if (path.name == '.env' or path.name.startswith('.env.') and path.name != '.env.example'
                or path.suffix in ('.key', '.pem')):
            errors.append(f'{name}: credential-like file requires exclusion')
    count = 0
    has_head = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', 'HEAD'], cwd=root, capture_output=True).returncode == 0
    if history and has_head:
        objects = git(root, 'rev-list', '--objects', '--all').decode().splitlines()
        for line in objects:
            oid = line.split(' ', 1)[0]
            if git(root, 'cat-file', '-t', oid).strip() == b'blob':
                inspect(git(root, 'cat-file', 'blob', oid), f'history blob {oid[:12]}', errors)
                count += 1
        for line in git(root, 'log', '--all', '--format=%an <%ae>%n%cn <%ce>').decode().splitlines():
            if expected_author is not None and line != expected_author:
                errors.append('history: unexpected author or committer identity')
    return sorted(set(errors)), len(names), count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-history', action='store_true')
    parser.add_argument('--check-initial-author', action='store_true', help='require the original public snapshot author; not a restriction on future contributors')
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors, files, blobs = audit(args.root.resolve(), not args.no_history, AUTHOR if args.check_initial_author else None)
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Cannot complete audit: {exc}\n')
    print(f'Checked {files} export files and {blobs} history blobs (heuristic, not a guarantee).')
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))
