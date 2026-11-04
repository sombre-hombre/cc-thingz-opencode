#!/usr/bin/env python3
"""Opt-in Task 7 smoke via native API and an explicitly authorized parent model.

Reads only parent metadata. Never changes parent, credentials, global config or
service lifecycle. Retains temporary sessions and evidence for inspection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api as native_api


def validate_calls(calls, work, plan):
    children = [p for p in calls if p["name"] == "subagent"]
    assert len(children) == 2, "expected exactly two task children"
    for child in children:
        assert child["state"]["status"] == "completed", child
        inp = child["state"]["input"]
        assert inp["agent"] == "general" and not inp.get("background") and not inp.get("sessionID"), inp
        assert str(work) in inp["prompt"] and str(plan) in inp["prompt"], inp
    assert children[0]["time"]["completed"] <= children[1]["time"]["ran"], "parallel task loop"
    return children


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, help="authorized parent: metadata read only")
    parser.add_argument("--authorize-current-model", action="store_true", required=True)
    parser.add_argument("--binary", default="opencode")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-exec-active.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)

    def save(name, data):
        (run / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")

    def api(method, path, body=None):
        return native_api(method, path, body, timeout=1200, executable=args.binary)

    sid = None
    try:
        # Refuse to turn this opt-in retry into an implicit service start.
        subprocess.run([args.binary, "service", "status"], check=True,
                       capture_output=True, text=True, timeout=30)
        info = api("GET", "/api/info")
        parent = api("GET", f"/api/session/{args.parent}")["data"]
        model = parent["model"]
        assert model.get("providerID") and model.get("id"), "parent has no active model"
        save("authorization-metadata", {"parentID": args.parent, "model": model,
             "version": info["version"], "parent_mutated": False})
        bundle = run / "bundle with spaces"
        for name in ("plugins", "scripts"):
            shutil.copytree(root / name, bundle / name)
        work = run / "workspace with spaces"
        work.mkdir()
        config = work / ".opencode"
        (config / "skills").mkdir(parents=True)
        (config / "skills/exec").symlink_to(bundle / "plugins/planning/skills/exec")
        (config / "commands").mkdir()
        shutil.copyfile(root / "commands/exec.md", config / "commands/exec.md")
        (work / "opencode.json").write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json", "snapshots": False,
            "skills": [str(config / "skills")],
            "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
        }, indent=2) + "\n")
        plan = work / "docs/plans/two-tasks.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("""# Dependent task smoke
## Overview
Create a seed then consume it. Validate exact bytes using Python.
### Task 1: Produce seed
- [ ] Write seed.txt containing exactly ALPHA followed by newline; validate its bytes with Python, commit seed.txt and this plan only.
### Task 2: Consume seed
- [ ] Read Task 1 seed.txt and create result.txt containing its stripped value plus -BETA followed by newline; assert result.txt equals ALPHA-BETA newline using Python; commit result.txt and this plan only.
""")
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

        def git(*argv):
            return subprocess.check_output(["git", *argv], cwd=work, env=env, text=True)

        git("init", "-q", "-b", "main")
        git("config", "user.name", "Exec smoke")
        git("config", "user.email", "smoke@example.invalid")
        git("add", ".opencode", "opencode.json", "docs/plans/two-tasks.md")
        git("commit", "-qm", "fixture")
        (work / "foreign.txt").write_text("not owned by tasks\n")
        git("add", "foreign.txt")
        sid = api("POST", "/api/session", {"title": "Task7 active model validation",
            "agent": "build", "location": {"directory": str(work)}, "model": model,
            "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]})["data"]["id"]
        save("smoke-session", {"id": sid, "directory": str(work), "model": model})
        deadline = time.monotonic() + 30
        while True:
            skills = api("GET", "/api/skill?" + urlencode({"location[directory]": str(work)}))
            exec_skill = next((s for s in skills["data"] if s["id"] == "exec"), None)
            if exec_skill and (str(bundle) in exec_skill["path"] or str(config) in exec_skill["path"]):
                break
            assert time.monotonic() < deadline, "project exec discovery timeout"
            time.sleep(.2)
        save("exec-discovery", exec_skill)
        assert str(bundle) in json.dumps(exec_skill) or str(config) in json.dumps(exec_skill), exec_skill
        source = bundle / "plugins/planning/skills/exec/SKILL.md"
        save("source", {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        api("POST", f"/api/session/{sid}/command", {"name": "exec", "text":
            f"Execute ONLY task-loop of plan {plan}. Explicitly agreed in-place, no worktree. "
            "All answers settled, no questions. Default settings, no custom rules. "
            "Use exactly one fresh general child at a time, await it before next dispatch. "
            "Stop at pending Task 9 review boundary. Preserve foreign.txt staged, do not commit it. "
            "No reviews, external commands, finalize, stats or move-plan. Do not edit code as parent. "
            "Use the project exec skill, not the old global definition; canonical bundle is " + str(bundle)})
        try:
            api("POST", f"/api/experimental/session/{sid}/wait", {})
        finally:
            transcript = api("GET", f"/api/session/{sid}/context")
            save("parent-context", transcript)
        errors = [m["error"] for m in transcript["data"] if m.get("type") == "idle" and m.get("error")]
        assert not errors, errors
        calls = [p for m in transcript["data"] for p in m.get("content", []) if p.get("type") == "tool"]
        children = validate_calls(calls, work, plan)
        save("child-calls", children)
        progress_paths = [re.search(r"^Progress: (.+)$", c["state"]["input"]["prompt"], re.M).group(1)
                          for c in children]
        assert progress_paths[0] == progress_paths[1], "children must share durable progress"
        progress = Path(progress_paths[0])
        assert progress.is_absolute() and str(progress).startswith("/tmp/opencode/"), progress
        progress_text = progress.read_text()
        (run / "progress-evidence.txt").write_text(progress_text)
        child_sessions = api("GET", "/api/session?" + urlencode({"parentID": sid}))
        save("child-sessions", child_sessions)
        assert len(child_sessions["data"]) == 2, "expected two fresh sessions"
        for child in child_sessions["data"]:
            assert child["location"]["directory"] == str(work), child
            assert child["model"] == model, child["model"]
            save(child["id"] + "-context", api("GET", f'/api/session/{child["id"]}/context'))
        assert (work / "seed.txt").read_bytes() == b"ALPHA\n"
        assert (work / "result.txt").read_bytes() == b"ALPHA-BETA\n"
        assert "[ ]" not in plan.read_text() and not (plan.parent / "completed").exists()
        assert git("diff", "--cached", "--name-only").strip() == "foreign.txt"
        assert int(git("rev-list", "--count", "HEAD")) == 3, "expected two task commits"
        commits = [set(git("show", "--pretty=", "--name-only", ref).splitlines()) for ref in ("HEAD~1", "HEAD")]
        assert commits == [{"seed.txt", "docs/plans/two-tasks.md"}, {"result.txt", "docs/plans/two-tasks.md"}], commits
        first_plan = git("show", "HEAD~1:docs/plans/two-tasks.md")
        assert first_plan.count("[x]") == 1 and first_plan.count("[ ]") == 1, first_plan
        for ref in ("HEAD~1", "HEAD"):
            commit = git("rev-parse", ref).strip()
            assert commit[:7] in progress_text, "progress missing actual task commit"
        assert "ALPHA" in progress_text and "Task 9" in progress_text, "missing validation/review-pending progress"
        save("results", {"model_smoke": "passed", "ordered_children": 2,
            "dependency": "ALPHA-BETA", "reviews": "pending Task 9", "commits": [sorted(c) for c in commits]})
        (run / "git-evidence.txt").write_text(git("log", "-3", "--stat") + git("status", "--short"))
        print("PASS real model two-task sequential loop", flush=True)
    except Exception as exc:
        (run / "failure.txt").write_text(repr(exc) + "\n")
        if sid:
            save("failure-context", api("GET", f"/api/session/{sid}/context"))
        raise


if __name__ == "__main__":
    main()
