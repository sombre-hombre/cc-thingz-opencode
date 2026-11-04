#!/usr/bin/env python3
"""GitLab release preparation and guarded publication. MIT, cc-thingz port.

No implicit fetch/tag/push. Reuse Task 10's actual read-only glab transport.
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit


class ReleaseError(Exception):
    pass


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ReleaseError(f"{args[0]} failed (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def git(*args):
    return run(["git", *args])


def last_tag(match=False):
    git("rev-parse", "--verify", "HEAD")
    # An absent reachable tag is distinct from a broken repository/command.
    tags = git("tag", "--merged", "HEAD", "--list", "v*" if match else "*")
    if not tags:
        return None
    return git("describe", "--tags", "--abbrev=0", *(["--match", "v*"] if match else []))


def version(kind):
    if kind not in {"major", "minor", "hotfix"}:
        raise ReleaseError(f"invalid type: {kind}; release type required (major, minor, hotfix)")
    tag = last_tag(True)
    if tag is None:
        parts = [0, 0, 0]
    else:
        m = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", tag)
        if not m:
            raise ReleaseError(f"cannot parse version from {tag}")
        prerelease = tag.split("+", 1)[0].partition("-")[2]
        if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in prerelease.split(".")):
            raise ReleaseError(f"cannot parse version from {tag}")
        parts = list(map(int, m.groups()))
    index = {"major": 0, "minor": 1, "hotfix": 2}[kind]
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    return "v" + ".".join(map(str, parts))


def transport():
    source = Path(__file__).resolve().parents[4] / "review/skills/pr/scripts/gitlab-context.py"
    if not source.is_file():
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        source = config / "opencode/skills/pr/scripts/gitlab-context.py"
    spec = importlib.util.spec_from_file_location("gitlab_context", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target():
    git("rev-parse", "--show-toplevel")
    remote = git("remote", "get-url", "origin")
    if "://" in remote:
        parsed = urlsplit(remote)
        if parsed.scheme not in {"https", "http", "ssh"} or parsed.password or parsed.query or parsed.fragment:
            raise ReleaseError("unsupported origin URL")
        host, path = parsed.hostname, parsed.path.lstrip("/")
        if parsed.port and parsed.scheme != "ssh":
            raise ReleaseError("nonstandard HTTP port: use existing glab API-host mapping")
    else:
        m = re.fullmatch(r"(?:[^/@:]+@)?([A-Za-z0-9.-]+):(.+)", remote)
        if not m:
            raise ReleaseError("origin must identify an explicit GitLab host/project")
        host, path = m.groups()
    path = path.removesuffix(".git").rstrip("/")
    if not host or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host) or len(path.split("/")) < 2 or any(p in {"", ".", ".."} for p in path.split("/")) or re.search(r"[%?#\s]", path):
        raise ReleaseError("invalid unencoded GitLab host/project")
    api = transport().api
    project = api(host, "projects/" + quote(path, safe=""))
    if type(project.get("id")) is not int or project["id"] <= 0 or project.get("path_with_namespace") != path:
        raise ReleaseError("GitLab project identity mismatch")
    return {"host": host, "project": path, "project_id": project["id"],
            "repo": f"https://{host}/{path}", "origin": remote}


def timestamp(value):
    if not isinstance(value, str):
        raise ReleaseError("missing merged_at/tag timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ReleaseError("timestamp has no timezone")
    return parsed


def clean_description(text):
    return re.sub(r"^(feat|fix|refactor|perf|chore|docs|style|build|ci|test)(\([^)]*\))?\s*:\s*", "", text)


def notes(info):
    tag = last_tag(True)
    cutoff = None
    if tag:
        cutoff = timestamp(git("for-each-ref", "--format=%(creatordate:iso-strict)", f"refs/tags/{tag}"))
    rows = transport().api(info["host"], f"projects/{info['project_id']}/merge_requests?state=merged&scope=all&per_page=100", many=True)
    entries = []
    # Validate every response before filtering: missing keys must never mean no MRs.
    for row in rows:
        if type(row.get("iid")) is not int or row["iid"] <= 0 or row.get("state") != "merged" or row.get("project_id") != info["project_id"] or not isinstance(row.get("title"), str) or not row["title"].strip() or not isinstance(row.get("author"), dict) or not isinstance(row["author"].get("username"), str) or not row["author"]["username"]:
            raise ReleaseError("invalid merged MR metadata")
        merged = timestamp(row.get("merged_at"))
        if cutoff is None or merged > cutoff:
            entries.append((row["title"], f"!{row['iid']} @{row['author']['username']}"))
    args = ["log", "--no-merges", "--format=%h%x09%s"]
    args += [f"{tag}..HEAD"] if tag else ["-20", "HEAD"]
    for line in git(*args).splitlines():
        oid, title = line.split("\t", 1)
        entries.append((title, oid))
    groups = {name: [] for name in ("New Features", "Improvements", "Bug Fixes", "Other")}
    seen = set()
    for title, suffix in entries:
        desc = clean_description(title)
        if desc in seen:
            continue  # MRs precede commits, preserving preferred author/IID evidence.
        seen.add(desc)
        lower = title.lower()
        group = "New Features" if lower.startswith("feat") else "Bug Fixes" if lower.startswith("fix") else "Improvements" if re.match(r"^(refactor|perf|chore|docs|style|build|ci|test)", lower) else "Other"
        groups[group].append(f"- {' '.join(desc.splitlines())} {suffix}")
    return "\n\n".join(f"**{name}**\n" + "\n".join(items) for name, items in groups.items() if items)


def preview(kind):
    if git("status", "--porcelain"):
        raise ReleaseError("uncommitted changes: commit or stash explicitly first")
    info = target()
    new = version(kind)
    if git("tag", "--list", new):
        raise ReleaseError(f"tag {new} already exists")
    return {"state": "preview-only", **info, "directory": git("rev-parse", "--show-toplevel"),
            "head": git("rev-parse", "HEAD"), "last_tag": last_tag(True), "version": new,
            "title": f"Version {new[1:]}", "notes": notes(info),
            "changelog": next((f for f in ("CHANGELOG.md", "changelog.md", "CHANGELOG") if Path(f).is_file()), None)}


def publish(path, confirmation):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    expected = f"{data['version']}@{hashlib.sha256(raw).hexdigest()}"
    if confirmation != expected:
        raise ReleaseError("explicit confirmation of this exact preview required")
    if data["state"] != "preview-only" or git("rev-parse", "--show-toplevel") != data["directory"] or git("rev-parse", "HEAD") != data["head"] or git("status", "--porcelain"):
        raise ReleaseError("preview stale: repository/HEAD/worktree changed")
    info = target()
    if any(info[k] != data[k] for k in info):
        raise ReleaseError("preview stale: GitLab target changed")
    tag = data["version"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or data["title"] != f"Version {tag[1:]}":
        raise ReleaseError("invalid preview version/title")
    if not data["notes"].strip():
        raise ReleaseError("empty notes: revise and reconfirm preview")
    if git("cat-file", "-t", f"refs/tags/{tag}") != "tag" or git("rev-parse", f"refs/tags/{tag}^{{}}") != data["head"]:
        raise ReleaseError("expected annotated local tag at confirmed HEAD")
    remote_tag = transport().api(info["host"], f"projects/{info['project_id']}/repository/tags/{quote(tag, safe='')}")
    if remote_tag.get("name") != tag or remote_tag.get("commit", {}).get("id") != data["head"] or not remote_tag.get("message"):
        raise ReleaseError("remote annotated tag does not match preview")
    # --no-update prevents glab's default update-existing-release behavior.
    run(["glab", "release", "create", tag, "--repo", info["repo"], "--name", data["title"],
         "--notes", data["notes"], "--ref", data["head"], "--no-update", "--no-close-milestone"])
    result = transport().api(info["host"], f"projects/{info['project_id']}/releases/{tag}")
    if result.get("tag_name") != tag or result.get("name") != data["title"] or result.get("description") != data["notes"] or result.get("commit", {}).get("id") != data["head"]:
        raise ReleaseError("release command returned but readback mismatch; inspect remote before retry")
    return result


def last_table():
    tag = last_tag()
    if not tag:
        return "No tags found in repository"
    raw = git("log", f"{tag}..HEAD", "--format=%ad%x00%an%x00%h%x00%s", "--date=short")
    if not raw:
        return f"Last tag: {tag}\nNo commits since this tag"
    rows = [line.split("\0", 3) for line in raw.splitlines()]
    authors = {r[1] for r in rows}
    single = len(authors) == 1
    output = [f"Last tag: {tag}"]
    if single:
        output.append(f"Author: {rows[0][1]}")
    output += ["", "| Date | Commit | Description |" if single else "| Date | Author | Commit | Description |",
               "|---|---|---|" if single else "|---|---|---|---|"]
    for row in rows:
        values = [row[0], row[2], row[3]] if single else row
        output.append("| " + " | ".join(v.replace("|", "\\|") for v in values) + " |")
    return "\n".join(output)


def details(selected):
    tag = last_tag()
    if not tag:
        raise ReleaseError("No tags found in repository")
    allowed = git("log", f"{tag}..HEAD", "--format=%H").splitlines()
    if selected == "all":
        oids = allowed
    else:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", selected):
            raise ReleaseError("specific commit must be a displayed hash")
        oid = git("rev-parse", "--verify", f"{selected}^{{commit}}")
        if oid not in allowed:
            raise ReleaseError("commit is outside the displayed range")
        oids = [oid]
    return "\n\n".join(git("show", "--stat", "--format=Commit: %h%nAuthor: %an <%ae>%nDate: %ad%n%n%s%n%n%b", "--date=short", oid, "--") for oid in oids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("detect", "notes", "last-tag"):
        sub.add_parser(action)
    sub.add_parser("version").add_argument("kind")
    sub.add_parser("preview").add_argument("kind")
    sub.add_parser("details").add_argument("commit")
    pub = sub.add_parser("publish")
    pub.add_argument("preview")
    pub.add_argument("--confirm", required=True)
    args = parser.parse_args()
    try:
        if args.action == "version":
            result = version(args.kind)
        elif args.action == "detect":
            target()
            result = "gitlab"
        elif args.action == "notes":
            result = notes(target())
        elif args.action == "preview":
            result = preview(args.kind)
        elif args.action == "publish":
            result = publish(args.preview, args.confirm)
        elif args.action == "details":
            result = details(args.commit)
        else:
            result = last_table()
        print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result)
        return 0
    except Exception as exc:
        # Also catches the shared transport's ContextError; never partial stdout.
        print(f"release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
