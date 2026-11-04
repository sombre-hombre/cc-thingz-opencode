#!/usr/bin/env python3
"""Opt-in real model planning smoke; owns its server/config, never launches children."""
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
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-planning-handoff.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(run)}
    for key, name in [("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                      ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                      ("XDG_CACHE_HOME", "cache")]:
        (run / name).mkdir()
        env[key] = str(run / name)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTHOR_NAME="Planning smoke", GIT_AUTHOR_EMAIL="smoke@example.invalid",
               GIT_COMMITTER_NAME="Planning smoke", GIT_COMMITTER_EMAIL="smoke@example.invalid")
    work = run / "workspace with spaces"
    work.mkdir()
    bundle = run / "bundle with spaces"
    for name in ("plugins", "commands", "scripts"):
        shutil.copytree(root / name, bundle / name)
    manifest = json.loads((root / "install-manifest.json").read_text())
    config = run / "config/opencode"
    for group in ("skills", "agents", "commands"):
        for entry in manifest[group]:
            target = config / entry["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(bundle / entry["source"])
    (work / "counter.py").write_text("def parse_count(value):\n    return int(value)\n")
    (work / "README.md").write_text("Small Python count parser. Test command: python3 -m unittest discover -s tests\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, env=env, check=True)
    subprocess.run(["git", "add", "counter.py", "README.md"], cwd=work, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=work, env=env, check=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (run / "server-stderr.log").open("w") as stderr:
        proc = subprocess.Popen([str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                cwd=work, env=env, stdout=subprocess.PIPE, stderr=stderr)
        try:
            password = None
            startup = b""
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
                    raise RuntimeError("isolated server exited")
            if not password:
                raise RuntimeError("server startup timeout")
            auth = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()

            def api(method, path, body=None):
                req = urllib.request.Request(f"http://127.0.0.1:{port}" + path, method=method,
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                    data=None if body is None else json.dumps(body).encode())
                with urllib.request.urlopen(req, timeout=600) as response:
                    data = response.read()
                    return json.loads(data) if data else None

            def save(name, data):
                (run / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")

            assert api("GET", "/api/info")["version"] == "2.1.1"
            deadline = time.monotonic() + 20
            while True:
                skills = api("GET", "/api/skill")["data"]
                if any(s["id"] == "make" for s in skills):
                    break
                assert time.monotonic() < deadline, "skills not discovered"
                time.sleep(.2)

            def session(title):
                return api("POST", "/api/session", {"title": title, "location": {"directory": str(work)},
                    "permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}],
                    "model": {"providerID": "opencode", "id": "big-pickle"}})["data"]["id"]

            def finish(sid, name):
                try:
                    api("POST", f"/api/experimental/session/{sid}/wait", {})
                finally:
                    transcript = api("GET", f"/api/session/{sid}/context")
                    save(name, transcript)
                calls = [p for m in transcript["data"] for p in m.get("content", []) if p.get("type") == "tool"]
                assert not [p for p in calls if p["name"] == "question"], "repeated agreed question"
                assert not [p for p in calls if p["name"] == "subagent" and p["state"]["status"] == "completed"], "child launched"
                errors = [m for m in transcript["data"] if m.get("type") == "idle" and m.get("error")]
                assert not errors, errors
                return transcript, calls

            agreed_context = (
                "Agreed context (all answers already settled): goal is reject non-positive counts in parse_count; "
                "scope counter.py and tests/test_counter.py plus README only; no dependencies, no CLI or API changes. "
                "Chosen approach: int conversion then >0 validation, ValueError for zero/negative/non-numeric input; "
                "positive integers preserved. Alternatives (custom parser, new validation library) rejected as unnecessary. "
                "Design fully validated: a single function with no state, no new components; tests cover success and errors. "
                "Testing preference Regular, python3 -m unittest discover -s tests. Title: Validate positive count. "
                "No custom rules, no unresolved questions. "
            )
            agreed = agreed_context + (
                "Create plan only, no implementation. "
                "After creation choose Done and commit only the plan, no auto or interactive review. "
                "Do not repeat agreed questions or ask next steps. "
            )
            direct_path = work / "docs/plans/direct plan.md"
            sid = session("Fresh direct make")
            api("POST", f"/api/session/{sid}/command", {"name": "make", "text": agreed + f"Explicit agreed plan path: {direct_path}."})
            _, calls = finish(sid, "direct-make")
            assert any(p["name"] == "skill" and p["state"].get("input") == {"id": "make"}
                       and p["state"]["status"] == "completed" for p in calls), "make not loaded"
            assert direct_path.is_file(), "direct plan not saved"
            validate_plan(direct_path)
            print("PASS fresh /make with agreed answers and path spaces", flush=True)

            handoff_path = work / "docs/plans/handoff plan.md"
            sid = session("Fresh brainstorm to make")
            mention = "@brainstorm"
            api("POST", f"/api/session/{sid}/prompt", {"text": mention + " " + agreed +
                f"Brainstorm phases 1–3 already validated above. Phase 4 choice Write plan is agreed. Plan path: {handoff_path}. Continue through make in this session.",
                "skills": [{"id": "brainstorm", "mention": {"start": 0, "end": len(mention), "text": mention}}]})
            _, calls = finish(sid, "brainstorm-make")
            assert any(p["name"] == "skill" and p["state"].get("input") == {"id": "make"}
                       and p["state"]["status"] == "completed" for p in calls), "no current-session handoff"
            assert handoff_path.is_file(), "handoff plan not saved"
            validate_plan(handoff_path)
            before = handoff_path.read_text()
            print("PASS brainstorm -> make current-session handoff, no repeated questions", flush=True)

            sid = session("Fresh plan revision")
            api("POST", f"/api/session/{sid}/command", {"name": "make", "text": agreed +
                f"Existing agreed plan: {handoff_path}. Revise only by appending a final line exactly 'COUNT-ZERO-REJECTED: zero raises ValueError'. "
                "Keep all previous text/tasks unchanged. This selected revision is approved; persist it, read back, Done, commit only this plan."})
            finish(sid, "revision")
            after = handoff_path.read_text()
            assert after.startswith(before.rstrip()), "agreed plan replaced"
            assert after.rstrip().endswith("COUNT-ZERO-REJECTED: zero raises ValueError"), "revision lost"
            print("PASS fresh revision reads existing plan and persists approved edit", flush=True)

            files_before = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*")
                            if p.is_file() and ".git" not in p.relative_to(work).parts}
            head_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, env=env)
            sid = session("Reviewer denied")
            api("POST", f"/api/session/{sid}/command", {"name": "make", "text": agreed_context +
                f"Current task is review-only: Auto review, external reviewer for existing plan {handoff_path}. "
                "Do not create any new plan, modify any file, implement or commit anything. "
                "Delegation is denied by session policy (no children allowed). "
                "Report review failed/unavailable, not clean or approved, and stop. No next-step questions."})
            transcript, _ = finish(sid, "reviewer-denied")
            text = "\n".join(p["text"] for m in transcript["data"] if m.get("type") == "assistant"
                             for p in m.get("content", []) if p.get("type") == "text").lower()
            assert any(word in text for word in ("failed", "unavailable", "denied")), text
            assert handoff_path.read_text() == after, "denied review modified plan"
            files_after = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*")
                           if p.is_file() and ".git" not in p.relative_to(work).parts}
            assert files_after == files_before, "review-only created/changed unrelated files"
            assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, env=env) == head_before, "review-only committed"
            save("results", {"direct": "passed", "handoff": "passed", "revision": "passed",
                             "reviewer_denied": "passed", "nested_agents": "not launched",
                             "interactive_revdiff": "not run - Task 5", "live_external_reviewer": "not run - Task 9"})
            print("PASS denied reviewer is not approval; no nested agents", flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def validate_plan(path):
    import re
    text = path.read_text()
    for heading in ("Overview", "Context", "Development Approach", "Testing Strategy",
                    "Progress Tracking", "Solution Overview", "Technical Details",
                    "Implementation Steps", "Post-Completion"):
        assert re.search(r"^## " + heading + r"\b", text, re.M), heading
    numbers = [int(n) for n in re.findall(r"^### Task (\d+):", text, re.M)]
    assert numbers and numbers == list(range(1, len(numbers) + 1)), numbers
    assert "counter.py" in text and "tests/test_counter.py" in text and "ValueError" in text
    assert not re.search(r"\$ARGUMENTS|CLAUDE_PLUGIN|Task N(?:-1)?:", text)


if __name__ == "__main__":
    main()
