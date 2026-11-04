#!/usr/bin/env python3
"""Opt-in two-task real V2 model smoke, with a private server/config/workspace."""
import argparse
import base64
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-exec-loop.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(run),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_AUTHOR_NAME": "Exec smoke", "GIT_AUTHOR_EMAIL": "smoke@example.invalid",
           "GIT_COMMITTER_NAME": "Exec smoke", "GIT_COMMITTER_EMAIL": "smoke@example.invalid"}
    for key, name in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                      ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache")):
        (run / name).mkdir()
        env[key] = str(run / name)
    bundle = run / "bundle with spaces"
    for name in ("plugins", "scripts", "commands"):
        shutil.copytree(root / name, bundle / name)
    config = run / "config/opencode"
    for group in ("skills", "commands", "agents"):
        for entry in json.loads((root / "install-manifest.json").read_text())[group]:
            dest = config / entry["target"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(bundle / entry["source"])
    work = run / "workspace with spaces"
    work.mkdir()
    plan = work / "docs/plans/two tasks.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("""# Dependent task smoke
## Overview
Create a seed then consume it. Validation: python3 -c assertions below.
### Task 1: Produce seed
- [ ] Write seed.txt containing exactly ALPHA followed by newline; validate its bytes with Python, commit seed.txt and this plan only.
### Task 2: Consume seed
- [ ] Read Task 1 seed.txt and create result.txt containing its stripped value plus -BETA followed by newline; assert result.txt equals ALPHA-BETA newline using Python; commit result.txt and this plan only.
""")
    def git(*argv):
        return subprocess.check_output(["git", *argv], cwd=work, env=env, text=True)
    git("init", "-q", "-b", "main")
    git("add", "docs/plans/two tasks.md")
    git("commit", "-qm", "fixture")
    # Preserve a foreign staged file through both task commits.
    (work / "foreign.txt").write_text("not owned by tasks\n")
    git("add", "foreign.txt")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (run / "server-stderr.log").open("w") as err:
        proc = subprocess.Popen([str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                cwd=work, env=env, stdout=subprocess.PIPE, stderr=err)
        try:
            startup, password = b"", None
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if select.select([proc.stdout], [], [], 1)[0]:
                    startup += os.read(proc.stdout.fileno(), 65536)
                    for line in startup.splitlines(keepends=True):
                        if line.startswith(b"server password ") and line.endswith(b"\n"):
                            password = line.decode().strip().removeprefix("server password ")
                    if password:
                        break
                if proc.poll() is not None:
                    raise RuntimeError("private server exited")
            if not password:
                raise RuntimeError("private server startup timeout")
            auth = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()
            def api(method, path, body=None):
                req = urllib.request.Request(f"http://127.0.0.1:{port}" + path, method=method,
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                    data=None if body is None else json.dumps(body).encode())
                with urllib.request.urlopen(req, timeout=900) as response:
                    data = response.read()
                    return json.loads(data) if data else None
            def save(name, value):
                (run / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")
            assert api("GET", "/api/info")["version"] == "2.1.1"
            deadline = time.monotonic() + 20
            while not any(s["id"] == "exec" for s in api("GET", "/api/skill")["data"]):
                assert time.monotonic() < deadline, "skill discovery timeout"
                time.sleep(.2)
            sid = api("POST", "/api/session", {"title": "Two dependent tasks",
                "location": {"directory": str(work)},
                "model": {"providerID": "opencode", "id": "big-pickle"},
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]})["data"]["id"]
            api("POST", f"/api/session/{sid}/command", {"name": "exec", "text":
                f"Execute ONLY task-loop of plan {plan}. Explicitly agreed in-place, no worktree. "
                "All answers settled, no questions. Default settings, no custom rules. "
                "Use exactly one fresh general child at a time, await it before next dispatch. "
                "Stop at pending Task 9 review boundary. Preserve foreign.txt staged, do not commit it. "
                "No reviews, external commands, finalize, stats or move-plan. Do not edit code as parent."})
            try:
                api("POST", f"/api/experimental/session/{sid}/wait", {})
            finally:
                transcript = api("GET", f"/api/session/{sid}/context")
                save("parent-context", transcript)
            errors = [m["error"] for m in transcript["data"] if m.get("type") == "idle" and m.get("error")]
            assert not errors, errors
            calls = [p for m in transcript["data"] for p in m.get("content", []) if p.get("type") == "tool"]
            children = [p for p in calls if p["name"] == "subagent"]
            save("child-calls", children)
            assert len(children) == 2, "expected exactly two task children"
            for child in children:
                assert child["state"]["status"] == "completed", child
                inp = child["state"]["input"]
                assert inp["agent"] == "general" and not inp.get("background") and not inp.get("sessionID"), inp
                assert str(work) in inp["prompt"] and str(plan) in inp["prompt"], inp
            assert children[0]["time"]["completed"] <= children[1]["time"]["ran"], "parallel task loop"
            assert (work / "seed.txt").read_bytes() == b"ALPHA\n"
            assert (work / "result.txt").read_bytes() == b"ALPHA-BETA\n"
            assert "[ ]" not in plan.read_text() and not (plan.parent / "completed").exists()
            assert git("diff", "--cached", "--name-only").strip() == "foreign.txt"
            assert int(git("rev-list", "--count", "HEAD")) == 3, "expected two task commits"
            save("results", {"model_smoke": "passed", "ordered_children": 2,
                             "dependency": "ALPHA-BETA", "reviews": "pending Task 9"})
            print("PASS real model two-task sequential loop", flush=True)
        except Exception as exc:
            (run / "failure.txt").write_text(repr(exc) + "\n")
            print(f"FAIL real model smoke: {exc}", flush=True)
            raise
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
