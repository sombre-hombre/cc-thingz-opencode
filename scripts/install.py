#!/usr/bin/env python3
"""Scoped manifest installer. Backups/state never live in scanned configuration.

copy snapshots the complete resource graph, then registers it using proven V2
symlinks (it is NOT a symlink-free fallback). No network or package installation.
Legacy replacements require an explicit reviewed inventory with exact hashes.
"""
import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid

GROUPS = ('skills', 'commands', 'agents', 'plugins')


def exists(p):
    return p.exists() or p.is_symlink()


def fingerprint(p):
    if not exists(p):
        return None
    h = hashlib.sha256()
    def visit(q, relative):
        mode = q.lstat().st_mode
        h.update(json.dumps([relative, stat.S_IMODE(mode)]).encode())
        if q.is_symlink():
            h.update(b'L' + os.fsencode(os.readlink(q)))
        elif q.is_file():
            h.update(b'F' + q.read_bytes())
        elif q.is_dir():
            h.update(b'D')
            for child in sorted(q.iterdir()):
                visit(child, relative + '/' + child.name)
        else:
            raise ValueError(f'unsupported file type: {q}')
    visit(p, '.')
    return h.hexdigest()


def relative(value):
    p = Path(value)
    if p.is_absolute() or '..' in p.parts or str(p) in ('', '.'):
        raise ValueError(f'unsafe relative path: {value}')
    return p


def safe_target(root, name):
    p = root / relative(name)
    for parent in p.parents:
        if parent == root:
            break
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f'unsafe target ancestor: {parent}')
    return p


def clone(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        dst.symlink_to(os.readlink(src))
    elif src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def remove(p):
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)  # only exact manifest-owned entry, after fingerprint guard


def save(p, data):
    temporary = p.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(p)


def rename_new(src, dst):
    """Atomic, same-filesystem rename without replacing an arriving user entry."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        # Darwin RENAME_EXCL: fail atomically if the destination already exists.
        function = getattr(libc, 'renamex_np', None)
        arguments = (os.fsencode(src), os.fsencode(dst), 4)
        signature = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    elif sys.platform.startswith('linux'):
        function = getattr(libc, 'renameat2', None)
        arguments = (-100, os.fsencode(src), -100, os.fsencode(dst), 1)
        signature = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    else:
        function = None
    if function is None:
        raise OSError(errno.ENOTSUP, 'atomic no-replace rename requires Linux or macOS')
    function.argtypes = signature
    function.restype = ctypes.c_int
    if function(*arguments):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(dst))


def transition(root, state, path, n, desired, source=None):
    item = state['entries'][n]
    p = safe_target(root, n)
    expected = fingerprint(p)
    verify_state(root, state)
    if expected == item[desired]:
        item['step'] = desired
        save(path, state)
        return
    displaced = Path(state['transaction']) / (uuid.uuid4().hex + '-displaced')
    staged = displaced.with_name(displaced.name + '-new')
    if source is not None:
        clone(source, staged)  # prepare before displacing a live entry
    item.update(step='transition', displaced=str(displaced), expected=expected, desired=desired)
    save(path, state)  # durable intent before either rename
    if exists(p):
        rename_new(p, displaced)
        if fingerprint(displaced) != expected:
            if not exists(p):
                rename_new(displaced, p)
            raise ValueError(f'target changed during replacement; displaced data retained: {n}')
    elif expected is not None:
        raise ValueError(f'target disappeared during replacement: {n}')
    if source is not None:
        rename_new(staged, p)
    item['step'] = desired
    save(path, state)


def restore(root, state, path):
    backup = Path(state['backup'])
    for n, item in state['entries'].items():
        if fingerprint(backup / relative(n)) != item['before']:
            raise ValueError(f'backup changed: {n}')
    # Old installed.json v1 files have no transaction or per-entry step.
    if 'transaction' not in state:
        root.parent.mkdir(parents=True, exist_ok=True)
        transaction = root.parent / ('.cc-thingz-' + uuid.uuid4().hex)
        transaction.mkdir(mode=0o700)
        state['transaction'] = str(transaction)
    state['phase'] = 'restoring'
    save(path, state)
    for n, item in state['entries'].items():
        transition(root, state, path, n, 'before', backup / n if item['before'] is not None else None)
    for name in reversed(state['createdDirs']):
        try:
            (root / relative(name)).rmdir()
        except OSError:
            pass  # unrelated new entries are retained
    state['phase'] = 'restored'
    save(path, state)


def load_manifest(source):
    m = json.loads((source / 'install-manifest.json').read_text())
    if m['version'] != 1:
        raise ValueError('unsupported manifest')
    entries = [e for g in GROUPS for e in m[g]]
    names = [e['target'] for e in entries] + m['retired']
    for name in names + m['snapshotOnly'] + m['legacyReplaceable']:
        relative(name)
    if len(names) != len(set(names)) or any(a != b and b.startswith(a + '/') for a in names for b in names):
        raise ValueError('overlapping targets')
    for e in entries:
        p = source / relative(e['source'])
        if not p.exists() or not p.resolve().is_relative_to(source):
            raise ValueError(f'missing/escaping source: {p}')
    return m, entries, names


def inventory(root, m, names):
    return {'target': str(root), 'entries': {n: fingerprint(safe_target(root, n))
            for n in names if exists(safe_target(root, n))},
            'snapshotOnly': {n: fingerprint(safe_target(root, n)) for n in m['snapshotOnly']}}


def verify_state(root, state):
    if state['target'] != str(root):
        raise ValueError('state belongs to a different target')
    for n, item in state['entries'].items():
        actual = fingerprint(safe_target(root, n))
        allowed = [item['installed']]
        if state['phase'] in ('installing', 'restoring'):
            allowed.append(item['before'])
            if item.get('step') == 'transition' and item.get('displaced'):
                displaced = Path(item['displaced'])
                if fingerprint(displaced) == item['expected']:
                    allowed.append(None)  # killed between the two renames
        if actual not in allowed:
            raise ValueError(f'foreign change; refusing to overwrite/remove: {n}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'install', 'restore'])
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--target-root', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'opencode')
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--replace-inventory', type=Path)
    parser.add_argument('--mode', choices=['symlink', 'copy'], default='symlink')
    args = parser.parse_args()
    source, root = args.source.resolve(), args.target_root.absolute()
    if root.is_symlink():
        raise ValueError('target root must not be a symlink')
    root = root.resolve()
    if args.action != 'restore':
        m, entries, names = load_manifest(source)
    if args.action == 'inventory':
        print(json.dumps(inventory(root, m, names), indent=2))
        return
    key = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    state_dir = (args.state_dir or Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'cc-thingz' / key).absolute()
    # Both directions: never put state in sources/config or sources inside state.
    state_dir = state_dir.resolve()
    if any(state_dir.is_relative_to(p) or p.is_relative_to(state_dir) for p in (root, source)):
        raise ValueError('state/backup must be outside config and source trees')
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The lock identity follows the target, not a caller-selected state directory.
    root.parent.mkdir(parents=True, exist_ok=True)
    with (root.parent / ('.cc-thingz-lock-' + key)).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = state_dir / 'installed.json'
        state = json.loads(path.read_text()) if path.exists() else None
        if state and state['phase'] != 'restored':
            verify_state(root, state)
            if args.action == 'install':
                if state['phase'] != 'installed' or state['source'] != str(source) or state['mode'] != args.mode:
                    raise ValueError('different/incomplete installation; restore first')
                print(json.dumps({'status': 'unchanged', 'manifest': str(path), 'backup': state['backup']}))
                return
        elif args.action == 'restore':
            if state and state['target'] != str(root):
                raise ValueError('state belongs to a different target')
            print(json.dumps({'status': 'already-restored' if state else 'not-installed'}))
            return
        if args.action == 'restore':
            backup = Path(state['backup'])
            restore(root, state, path)
            print(json.dumps({'status': 'restored', 'manifest': str(path), 'backup': str(backup)}))
            return
        current = inventory(root, m, names)
        approval = json.loads(args.replace_inventory.read_text()) if args.replace_inventory else {'entries': {}}
        if approval.get('entries'):
            if approval.get('target') != str(root) or approval != current:
                raise ValueError('replacement inventory does not match current target')
        for n in current['entries']:
            if n not in m['legacyReplaceable'] or approval['entries'].get(n) != current['entries'][n]:
                raise ValueError(f'conflict (not explicitly approved legacy entry): {n}')
        # SDK must already resolve beside the source package, not an obsolete global SDK.
        sdk = source / 'integrations/opencode/skill-eval/node_modules/@opencode/plugin/package.json'
        if not sdk.is_file() or json.loads(sdk.read_text()).get('version') != '2.1.1':
            raise ValueError(f'missing pinned SDK 2.1.1: {sdk}')
        run = state_dir / ('backup-' + uuid.uuid4().hex)
        run.mkdir(mode=0o700)
        backup = run / 'original'
        backup.mkdir()
        for n in list(current['entries']) + m['snapshotOnly']:
            p = safe_target(root, n)
            if exists(p):
                clone(p, backup / n)
        if current != inventory(root, m, names):
            raise ValueError('target changed during backup; nothing installed')
        for n, digest in current['entries'].items():
            if fingerprint(backup / n) != digest:
                raise ValueError(f'backup mismatch: {n}')
        base = source
        if args.mode == 'copy':
            base = run / 'package'
            base.mkdir()
            for n in ('plugins', 'scripts', 'commands', 'integrations', 'LICENSE', 'upstream.lock', 'install-manifest.json'):
                clone(source / n, base / n)
            # Materialize SDK dependencies too; no dangling dependency on temporary tools.
            nm = base / 'integrations/opencode/skill-eval/node_modules'
            if nm.is_symlink():
                nm.unlink()
                shutil.copytree(sdk.parents[2], nm, symlinks=False)
        if current != inventory(root, m, names):
            raise ValueError('target changed during package preparation; nothing installed')
        transaction = root.parent / ('.cc-thingz-' + uuid.uuid4().hex)
        transaction.mkdir(mode=0o700)
        state = {'version': 1, 'target': str(root), 'source': str(source), 'mode': args.mode,
                 'backup': str(backup), 'phase': 'installing', 'entries': {}, 'createdDirs': [],
                 'snapshotOnly': current['snapshotOnly'], 'transaction': str(transaction)}
        mapping = {e['target']: str(base / e['source']) for e in entries}
        for n in names:
            p = safe_target(root, n)
            # Expected ownership fingerprint can be computed before installing.
            probe = run / 'probe'
            if n in mapping:
                probe.symlink_to(mapping[n])
                installed = fingerprint(probe)
                probe.unlink()
            else:
                installed = None
            state['entries'][n] = {'before': current['entries'].get(n), 'installed': installed, 'step': 'before'}
        save(path, state)
        try:
            for n in names:
                p = safe_target(root, n)
                missing = []
                parent = p.parent
                while parent != root and not parent.exists():
                    missing.append(str(parent.relative_to(root)))
                    parent = parent.parent
                state['createdDirs'].extend(reversed(missing))
                save(path, state)
                p.parent.mkdir(parents=True, exist_ok=True)
                if fingerprint(p) != state['entries'][n]['before']:
                    raise ValueError(f'target changed before replacement: {n}')
                staged = transaction / 'next'
                if n in mapping:
                    staged.symlink_to(mapping[n])
                try:
                    transition(root, state, path, n, 'installed', staged if n in mapping else None)
                finally:
                    if staged.is_symlink():
                        staged.unlink()
            state['phase'] = 'installed'
            save(path, state)
        except BaseException:
            verify_state(root, state)  # never rollback over unapproved arrivals
            restore(root, state, path)
            raise
        print(json.dumps({'status': 'installed', 'manifest': str(path), 'backup': str(backup)}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f'install: {error}', file=sys.stderr)
        sys.exit(1)
