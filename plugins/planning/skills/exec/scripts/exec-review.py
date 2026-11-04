#!/usr/bin/env python3
"""V2 exec evidence boundaries; does not launch agents or drive phase order.

external REQUEST_JSON: exact argv launcher, separate streams, bounded process group.
stats ROOT_SESSION_ID: read authenticated native API for this root and descendants.
finalize-check REQUEST_JSON: read-only Git rewrite eligibility, never performs rebase.
"""
import datetime
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from urllib.parse import urlencode


def classify(returncode, stdout, stderr, timed_out=False):
    if timed_out:
        return {"state": "failed", "reason": "timeout", "has_blocking": False}
    if returncode:
        marker = next((line for line in stderr.splitlines() if "run-external-review:" in line), None)
        return {"state": "skipped" if returncode == 127 and marker else "failed",
                "reason": marker if returncode == 127 and marker else f"reviewer exit {returncode}: " +
                (stderr.splitlines()[-1] if stderr.splitlines() else "no stderr"), "has_blocking": False}
    blocking = bool(re.search(r"\b(CRITICAL|MAJOR)\b", stdout, re.I))
    clean = bool(re.search(r"^\s*NO ISSUES FOUND\s*$", stdout, re.M))
    failure = bool(re.search(r"^\s*(FAILED|ERROR|CANCELLED)\b", stdout, re.I | re.M))
    tagged = bool(re.search(r"\b(CRITICAL|MAJOR|MINOR)\b", stdout, re.I))
    if not stdout.strip():
        state, reason = "failed", "no output"
    elif failure:
        state, reason = "failed", "reviewer reported failure"
    elif tagged:
        state, reason = "findings", "blocking" if blocking else "minor-only"
    elif clean:
        state, reason = "clean", "NO ISSUES FOUND"
    else:
        state, reason = "failed", "no findings and no clean marker: " + stdout.splitlines()[0]
    return {"state": state, "reason": reason, "has_blocking": blocking}


def absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("absolute path required: " + str(path))
    return path


def external(request):
    cwd = absolute(request["cwd"])
    prompt = absolute(request["prompt_file"]).read_text()
    directory = absolute(request["output_dir"])
    command = request["command"]
    timeout = request.get("timeout", 3600)
    if not isinstance(command, str) or not prompt.strip():
        raise ValueError("command must be string and prompt nonempty")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive finite seconds")
    if not cwd.is_dir():
        raise ValueError("working directory missing")
    directory.mkdir(mode=0o700)  # no overwrite or shared iteration filenames
    out, err = directory / "review.out", directory / "review.err"
    timed_out = False
    cancelled = False
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    with out.open("w") as stdout, err.open("w") as stderr:
        previous = {sig: signal.signal(sig, interrupt)
                    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        process = None
        try:
            process = subprocess.Popen(["bash", str(Path(__file__).resolve().with_name("run-external-review.sh")),
                                     command, prompt], cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        except KeyboardInterrupt:
            cancelled = True
        finally:
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                # Also reap descendants when their wrapper exits before them.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    result = {**classify(process.returncode, out.read_text(errors="replace"),
                        err.read_text(errors="replace"), timed_out),
              "returncode": process.returncode, "timed_out": timed_out,
               "stdout_file": str(out), "stderr_file": str(err)}
    if cancelled:
        result.update(state="cancelled", reason="interrupted", has_blocking=False)
    (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def native_api(path):
    # Discovery/auth stays in the installed CLI, never reads credential files.
    # Installed CLI can exit before a >256KiB stdout PIPE is drained. A regular
    # file preserves the full JSON; do not truncate or silently accept partial data.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir="/tmp/opencode") as output:
        proc = subprocess.run(["opencode", "api", "get", path], stdout=output,
                              stderr=subprocess.PIPE, text=True, timeout=60)
        if proc.returncode:
            raise ValueError(f"API {path} exit {proc.returncode}: {proc.stderr.strip()}")
        output.seek(0)
        return json.load(output)


def stats(root, api=native_api):
    if not re.fullmatch(r"ses_[A-Za-z0-9]+", root):
        raise ValueError("explicit V2 root session ID required")
    result = {"root_session_id": root, "snapshot": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "sessions": [], "errors": [], "coverage": "complete", "scope": "own-session usage, before stats/completion"}
    pending, seen = [root], set()
    while pending:
        sid = pending.pop(0)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            session = api("/api/session/" + sid)["data"]
            if session["id"] != sid or (sid != root and session.get("parentID") not in seen):
                raise ValueError("unexpected session identity/ancestry")
            row = {key: session.get(key, "unavailable") for key in
                   ("id", "parentID", "title", "model", "tokens", "cost", "time", "location")}
            row["tool_scope"] = "visible context only; compacted historical calls unavailable"
            result["sessions"].append(row)
            try:
                context = api(f"/api/session/{sid}/context")["data"]
                row["tools"] = [{"name": p["name"], "time": p.get("time", "unavailable"),
                                  "status": p.get("state", {}).get("status", "unavailable"),
                                  "child_session_id": p.get("state", {}).get("metadata", {}).get("sessionID"),
                                  "description": p.get("state", {}).get("input", {}).get("description")}
                                 for m in context for p in m.get("content", []) if p.get("type") == "tool"]
            except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
                row["tools"] = "unavailable"
                result["errors"].append(f"{sid} context: {exc}")
            cursor, cursors = None, set()
            while True:
                query = {"parentID": sid, "limit": "100"}
                if cursor:
                    query["cursor"] = cursor
                page = api("/api/session?" + urlencode(query))
                for child in page["data"]:
                    if child.get("parentID") != sid:
                        raise ValueError("unexpected child ancestry")
                    pending.append(child["id"])
                cursor = (page.get("cursor") or {}).get("next")
                if not cursor:
                    break
                if cursor in cursors:
                    raise ValueError("repeated session pagination cursor")
                cursors.add(cursor)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
            result["errors"].append(f"{sid}: {exc}")
    if result["errors"]:
        result["coverage"] = "unavailable" if not result["sessions"] else "partial"
    return result


def finalize_check(request):
    cwd = absolute(request["cwd"])

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.PIPE).strip()

    if request.get("authorized") is not True:
        return {"state": "skipped", "reason": "no explicit rewrite authorization"}
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        path = Path(git("rev-parse", "--git-path", marker))
        if (path if path.is_absolute() else cwd / path).exists():
            return {"state": "skipped", "reason": "active VCS operation: " + marker}
    status = git("status", "--porcelain", "--untracked-files=all")
    if status:
        return {"state": "skipped", "reason": "dirty working tree/index", "status": status}
    base = git("rev-parse", "--verify", request["default_branch"] + "^{commit}")
    owned = request["owned_commits"]
    if not isinstance(owned, list) or any(not isinstance(c, str) or not re.fullmatch(r"[0-9a-f]{40,64}", c) for c in owned):
        raise ValueError("owned_commits must contain full recorded OIDs")
    commits = git("rev-list", base + "..HEAD").splitlines()
    foreign = sorted(set(commits) - set(owned))
    if foreign:
        return {"state": "skipped", "reason": "unrelated/unrecorded branch commits", "commits": foreign}
    return {"state": "ready", "base": base, "commits": commits}


def main():
    try:
        command, value = sys.argv[1:]
        if command == "stats":
            result = stats(value)
        elif command in ("external", "finalize-check"):
            request = json.loads(Path(value).read_text())
            result = external(request) if command == "external" else finalize_check(request)
        else:
            raise ValueError(__doc__)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("exec-review: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
