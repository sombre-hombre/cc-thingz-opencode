#!/usr/bin/env python3
"""Create an exec worktree at the explicit source HEAD; never move a session.

The caller performs native V2 session_move, then calls verify with its observed
directory. A failed create/move retains the owned run directory and manifest.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid


def git(source, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(source), *args],
        env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"}, stderr=subprocess.PIPE)


def snapshot(source):
    status = git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    digest = hashlib.sha256()
    for args in (("diff", "--binary", "--no-ext-diff", "--no-textconv"),
                 ("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv")):
        digest.update(git(source, *args))
    for name in git(source, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if name:
            path = source / os.fsdecode(name)
            digest.update(name + b"\0")
            mode = path.lstat().st_mode
            # Source state includes object type and permissions, not just bytes:
            # a link target string can equal the contents of a regular file.
            digest.update(str(mode).encode() + b"\0")
            digest.update(os.fsencode(os.readlink(path)) if stat.S_ISLNK(mode) else path.read_bytes())
    return {"head": git(source, "rev-parse", "HEAD").decode().strip(),
            "branch": git(source, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
            "status_hex": status.hex(), "dirty_sha256": digest.hexdigest()}


def create(source, plan, run):
    run = run.resolve()
    source = Path(os.fsdecode(git(source, "rev-parse", "--show-toplevel")).strip()).resolve()
    before = snapshot(source)
    if plan.is_symlink():
        raise ValueError("plan must not be a symlink")
    plan = plan.resolve(strict=True)
    relative = plan.relative_to(source)
    # Only a committed, byte-identical, clean plan can be present in the new tree.
    try:
        committed = git(source, "show", f"{before['head']}:{relative.as_posix()}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("plan must be committed in source HEAD before worktree creation") from exc
    if git(source, "status", "--porcelain=v1", "--", str(relative)) or plan.read_bytes() != committed:
        raise ValueError("plan must be committed and clean before worktree creation")
    if git(source, "ls-files", "-s", "--", str(relative)).startswith(b"120000 "):
        raise ValueError("plan must be a regular committed file, not a symlink")
    if run == source or source in run.parents:
        raise ValueError("run directory must be outside source tree")
    run.mkdir(parents=True, exist_ok=False)
    manifest = run / "worktree.json"
    record = {"state": "creating", "source": str(source), "before": before,
              "directory": str(run / "tree"), "plan_relative": str(relative),
              "plan_sha256": hashlib.sha256(committed).hexdigest()}
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    try:
        helper = Path(__file__).resolve().parent / "create-branch.sh"
        base = subprocess.check_output(["bash", str(helper), "--print-name", str(plan)], text=True).strip()
        branch = base
        while subprocess.run(["git", "-C", str(source), "show-ref", "--verify", "--quiet",
                              f"refs/heads/{branch}"], check=False).returncode == 0:
            branch = f"{base}-{uuid.uuid4().hex[:12]}"
        record["branch"] = branch
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        # Never checkout or rename a branch in source. HEAD is an immutable OID,
        # not main, canonical checkout HEAD, or a branch which can move mid-call.
        git(source, "worktree", "add", "-b", branch, record["directory"], before["head"])
        record["state"] = "created-session-move-pending"
        if snapshot(source) != before:
            raise ValueError("source changed during worktree creation; stop for inspection")
        target_plan = Path(record["directory"]) / relative
        if target_plan.read_bytes() != committed:
            raise ValueError("plan unavailable or different in worktree")
        record["plan"] = str(target_plan)
    except Exception as exc:
        detail = exc.stderr.decode(errors="replace") if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        record.update(state="failed", error=detail)
        raise
    finally:
        manifest.write_text(json.dumps(record, indent=2) + "\n")
    return {**record, "manifest": str(manifest)}


def verify(manifest, directory):
    record = json.loads(manifest.read_text())
    if record["state"] not in ("created-session-move-pending", "verified"):
        raise ValueError("worktree creation failed; inspect retained manifest")
    if directory.resolve() != Path(record["directory"]).resolve():
        raise ValueError("session directory does not match owned worktree; move failed")
    if snapshot(Path(record["source"])) != record["before"]:
        raise ValueError("source HEAD/branch/status/content changed; isolation breach")
    if not Path(record["plan"]).is_file():
        raise ValueError("plan is missing in worktree")
    return {**record, "observed_directory": str(directory.resolve()), "state": "verified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    for name in ("source", "plan", "run"):
        new.add_argument(name, type=Path)
    check = sub.add_parser("verify")
    check.add_argument("manifest", type=Path)
    check.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        paths = (args.source, args.plan, args.run) if args.command == "create" else (args.manifest, args.directory)
        if not all(p.is_absolute() for p in paths):
            raise ValueError("all paths must be absolute")
        result = create(*paths) if args.command == "create" else verify(*paths)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError) as exc:
        detail = exc.stderr.decode(errors="replace") if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"worktree: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
