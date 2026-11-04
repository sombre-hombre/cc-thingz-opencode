#!/usr/bin/env python3
"""Opt-in real V2 move + general-child smoke using native authenticated API only."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api as native_api


def validate(api, save, run, wt, parent_id):
    """Read existing evidence after wait; never re-dispatch a model on resume."""
    sid = json.loads((run / "session.json").read_text())["id"]
    auth = json.loads((run / "authorization.json").read_text())
    assert auth["parentID"] == parent_id
    model = auth["model"]
    evidence = json.loads((run / "before.json").read_text())
    source, main = Path(evidence["source"]), Path(evidence["canonical"])
    before, canonical_before = evidence["source_snapshot"], evidence["canonical_snapshot"]
    plan_relative = Path("docs/plans/20261103-isolated task.md")
    api("POST", f"/api/experimental/session/{sid}/wait", {})
    context = api("GET", f"/api/session/{sid}/context")
    save("context", context)
    errors = [m["error"] for m in context["data"] if m.get("type") == "idle" and m.get("error")]
    assert not errors, errors
    session = api("GET", f"/api/session/{sid}")["data"]
    save("result-session", session)
    work = Path(session["location"]["directory"])
    assert work != source and work != main and work.is_absolute()
    manifest = work.parent / "worktree.json"
    record = wt.verify(manifest, work)
    assert record["before"] == before
    assert record["branch"].startswith("isolated-task-")

    def git(*argv):
        return subprocess.check_output(["git", "-C", str(work), *argv], text=True)

    assert git("rev-parse", "HEAD~1").strip() == before["head"]
    assert (work / "child-only.txt").read_bytes() == b"ISOLATED\n"
    assert "[ ]" not in (work / plan_relative).read_text()
    assert not (source / "child-only.txt").exists() and not (main / "child-only.txt").exists()
    assert wt.snapshot(source) == before and wt.snapshot(main) == canonical_before
    assert "[ ]" in (source / plan_relative).read_text()
    assert set(git("show", "--pretty=", "--name-only", "HEAD").splitlines()) == {"child-only.txt", str(plan_relative)}
    children = api("GET", "/api/session?" + urlencode({"parentID": sid}))["data"]
    save("children", children)
    assert len(children) == 1 and children[0]["location"]["directory"] == str(work), children
    assert children[0]["model"] == model
    save("child-context", api("GET", f"/api/session/{children[0]['id']}/context"))
    calls = [p for m in context["data"] for p in m.get("content", []) if p.get("type") == "tool"]
    child_calls = [p for p in calls if p["name"] == "subagent"]
    assert len(child_calls) == 1 and child_calls[0]["state"]["status"] == "completed"
    child_input = child_calls[0]["state"]["input"]
    assert child_input["agent"] == "general" and not child_input.get("sessionID")
    assert str(work) in child_input["prompt"] and str(work / plan_relative) in child_input["prompt"]
    moves = [c for c in calls if c["state"]["status"] == "completed" and
             any(t.get("tool") == "opencode.session_move" and t["status"] == "completed"
                 for t in c["state"].get("metadata", {}).get("toolCalls", []))]
    assert len(moves) == 1, "expected exactly one actual native session_move"
    move = json.loads(next(p["text"] for p in moves[0]["state"]["content"] if p["type"] == "text"))
    assert move == {"sessionID": sid, "directory": str(work)}, move
    pwd_calls = [c for c in calls if c["name"] == "shell" and c["state"]["status"] == "completed"
                 and c["state"].get("input") == {"command": "pwd"}]
    assert len(pwd_calls) == 1 and any(p.get("text", "").strip() == str(work)
                                    for p in pwd_calls[0]["state"]["content"]), "actual shell pwd mismatch"
    assert api("GET", f"/api/session/{parent_id}")["data"]["location"] == auth["parent_location"]
    save("results", {"model_smoke": "passed", "model": model, "sessionID": sid,
         "childID": children[0]["id"], "session_directory": str(work),
         "source_head": before["head"], "canonical_head": canonical_before["head"],
         "source_unchanged": True, "canonical_unchanged": True, "branch": record["branch"],
         "manifest": str(manifest), "marker": "ISOLATED", "reviews": "pending Task9",
         "commit": git("rev-parse", "HEAD").strip(), "native_move": move,
         "shell_pwd": str(work), "source_status_hex": before["status_hex"]})
    print("PASS real V2 session_move and fresh general worktree write", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--authorize-current-model", required=True, action="store_true")
    parser.add_argument("--binary", default="opencode")
    parser.add_argument("--resume-artifacts", type=Path, help="wait/validate existing smoke only; no model redispatch")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("wt", root / "plugins/planning/skills/exec/scripts/worktree.py")
    wt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wt)
    run = args.resume_artifacts or Path(tempfile.mkdtemp(prefix="cc-thingz-worktree-active.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)

    def save(name, data):
        (run / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")

    def api(method, path, body=None):
        return native_api(method, path, body, timeout=1200, executable=args.binary)

    sid = None
    try:
        subprocess.run([args.binary, "service", "status"], check=True, capture_output=True, timeout=30)
        if args.resume_artifacts:
            sid = json.loads((run / "session.json").read_text())["id"]
            validate(api, save, run, wt, args.parent)
            return
        parent = api("GET", f"/api/session/{args.parent}")["data"]
        parent_location = parent["location"]
        model = parent["model"]
        assert model == {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "medium"}, model
        save("authorization", {"parentID": args.parent, "model": model, "parent_location": parent_location})
        bundle = run / "bundle with spaces"
        for name in ("plugins", "scripts"):
            shutil.copytree(root / name, bundle / name)
        main = run / "canonical main"
        main.mkdir()
        config = main / ".opencode"
        (config / "skills").mkdir(parents=True)
        (config / "skills/exec").symlink_to(bundle / "plugins/planning/skills/exec")
        (config / "commands").mkdir()
        shutil.copyfile(root / "commands/exec.md", config / "commands/exec.md")
        (main / "opencode.json").write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json", "snapshots": False,
            "skills": [str(config / "skills")],
            "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
        }) + "\n")
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

        def git(directory, *argv):
            return subprocess.check_output(["git", "-C", str(directory), *argv], env=env, text=True)

        git(main, "init", "-q", "-b", "main")
        git(main, "config", "user.name", "Worktree smoke")
        git(main, "config", "user.email", "smoke@example.invalid")
        (main / "base.txt").write_text("canonical\n")
        git(main, "add", ".")
        git(main, "commit", "-qm", "canonical fixture")
        source = run / "feature source with spaces"
        git(main, "worktree", "add", "-qb", "source-feature", str(source))
        plan_relative = Path("docs/plans/20261103-isolated task.md")
        plan = source / plan_relative
        plan.parent.mkdir(parents=True)
        plan.write_text("""# Isolation smoke
### Task 1: Isolated marker
- [ ] Read feature-only.txt (must contain FEATURE newline), write child-only.txt containing ISOLATED newline; validate both exact bytes using Python; commit child-only.txt and this plan only. Never write to the source checkout.
""")
        (source / "feature-only.txt").write_text("FEATURE\n")
        git(source, "add", ".")
        git(source, "commit", "-qm", "feature-only committed plan")
        git(source, "branch", "isolated-task", "main")
        (source / "foreign staged.txt").write_text("foreign staged\n")
        git(source, "add", "foreign staged.txt")
        (source / "base.txt").write_text("foreign unstaged\n")
        (source / "foreign untracked.txt").write_text("foreign untracked\n")
        before = wt.snapshot(source)
        canonical_before = wt.snapshot(main)
        save("before", {"source": str(source), "source_snapshot": before,
                         "canonical": str(main), "canonical_snapshot": canonical_before})
        sid = api("POST", "/api/session", {"title": "Task8 isolated worktree validation",
            "agent": "build", "location": {"directory": str(source)}, "model": model,
            "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]})["data"]["id"]
        save("session", {"id": sid})
        deadline = time.monotonic() + 30
        while True:
            registry = api("GET", "/api/skill?" + urlencode({"location[directory]": str(source)}))["data"]
            skill = next((s for s in registry if s["id"] == "exec"), None)
            if skill and Path(skill["path"]).resolve() == bundle / "plugins/planning/skills/exec/SKILL.md":
                break
            assert time.monotonic() < deadline, "project exec discovery timeout"
            time.sleep(.2)
        save("discovery", skill)
        # Actual failure route, on this new test session only: missing directory.
        try:
            result = api("POST", f"/api/session/{sid}/move", {"directory": str(run / "missing-directory")})
        except RuntimeError as exc:
            save("move-failure", {"error": str(exc)})
        else:
            save("move-failure", result)
            assert result.get("error") or result.get("type") == "error", result
        assert api("GET", f"/api/session/{sid}")["data"]["location"]["directory"] == str(source)
        api("POST", f"/api/session/{sid}/command", {"name": "exec", "text":
            f"Execute ONLY task-loop of {plan}. Explicit agreed choice: Move to worktree, NOT in-place. "
            "All answers settled; no questions. Use the project exec skill from " + str(bundle) + ". "
            "Read its Task8 worktree playbook. Source is a secondary feature checkout; canonical main is different. "
            "Source dirty files must remain unchanged; plan is committed/clean. Existing isolated-task branch "
            "is a collision, create a unique new branch from actual source HEAD. "
            "Use absolute worktree helper, native Code Mode session_move on THIS smoke session only, "
            "then exactly one fresh general child in the moved directory. Confirm shell pwd after move "
            "without explicit workdir, and check actual child directory via native API if needed. "
            "Stop before Task9 review; no reviews/finalize/stats/move-plan. No parent/caller session moves. "
            "At end report manifest path and verify original source guard. Never edit task files as parent."})
        validate(api, save, run, wt, args.parent)
    except Exception as exc:
        (run / "failure.txt").write_text(repr(exc) + "\n")
        if sid:
            save("failure-context", api("GET", f"/api/session/{sid}/context"))
        raise


if __name__ == "__main__":
    main()
