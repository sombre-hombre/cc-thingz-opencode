#!/usr/bin/env python3
"""Read-only GitLab review snapshot through glab 1.124; no publish operations.

MIT; part of the cc-thingz OpenCode port. glab owns authentication/pagination.
"""
import argparse
import json
import re
import subprocess
import sys
from urllib.parse import quote


class ContextError(Exception):
    pass


def api(host, endpoint, *, many=False, optional=False):
    args = ["glab", "api", "--hostname", host, "--method", "GET", endpoint]
    if many:
        args += ["--paginate", "--output", "ndjson"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        # Never reinterpret auth/network/rate-limit errors as missing features.
        status = re.search(r"(?:HTTP[ /]|status(?: code)?[ :]+)(\d{3})\b", result.stderr, re.I)
        if optional and status and status[1] in {"403", "404"}:
            return {"available": False, "http_status": int(status[1]),
                    "reason": "not accessible or not supported by this edition/version"}
        raise ContextError(f"GET {endpoint} failed (exit {result.returncode}): {result.stderr.strip()}")
    try:
        if many:
            value = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            if any(not isinstance(item, dict) for item in value):
                raise ValueError("expected NDJSON objects, not page arrays")
        else:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError("expected an object")
    except (ValueError, TypeError) as exc:
        raise ContextError(f"GET {endpoint}: invalid response: {exc}") from exc
    return {"available": True, "data": value} if optional else value


def snapshot(host, project, kind, iid):
    project_data = api(host, "projects/" + quote(project, safe=""))
    pid = project_data.get("id")
    if type(pid) is not int or pid <= 0:
        raise ContextError("project response has no numeric project ID")
    user = api(host, "user")
    if type(user.get("id")) is not int:
        raise ContextError("authenticated user response has no user ID")
    root = f"projects/{pid}/{'merge_requests' if kind == 'mr' else 'issues'}/{iid}"
    metadata = api(host, root)
    if metadata.get("iid") != iid or metadata.get("project_id") != pid:
        raise ContextError("target IID/project mismatch; never substitute global target ID")
    data = {"host": host, "project": project_data, "current_user": user,
            "kind": kind, "iid": iid, "metadata": metadata}
    # Notes and discussions overlap: retain originals; deduplicate by note ID in summaries.
    for name in ("notes", "discussions"):
        data[name] = api(host, root + f"/{name}?per_page=100", many=True)
    if kind == "mr":
        for name in ("diffs", "commits", "pipelines"):
            data[name] = api(host, root + f"/{name}?per_page=100", many=True)
        for name in ("approvals", "approval_state"):
            data[name] = api(host, root + "/" + name, optional=True)
        after = api(host, root)
        if not metadata.get("sha") or metadata["sha"] != after.get("sha") or metadata.get("diff_refs") != after.get("diff_refs"):
            raise ContextError("MR changed while fetching context; fetch a fresh snapshot")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="explicit GitLab hostname (existing glab API-host mapping is honored)")
    parser.add_argument("--project", required=True, help="unencoded full namespace/path, or numeric project ID")
    parser.add_argument("--kind", choices=("mr", "issue"), required=True)
    parser.add_argument("--iid", type=int, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", args.host):
        parser.error("host must be a hostname, not a URL or credentials")
    if args.iid <= 0 or not args.project or any(p in {"", ".", ".."} for p in args.project.split("/")) or re.search(r"[%?#\s]", args.project):
        parser.error("positive IID and unencoded project path/ID required")
    try:
        data = snapshot(args.host, args.project, args.kind, args.iid)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except (ContextError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"gitlab-context: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
