#!/usr/bin/env python3
"""Opt-in Task9 real main-orchestrator fanout/fixer/recheck through active service.

Read caller metadata only. New isolated project/session, retained evidence.
Resume waits/validates the SAME session, never redispatches a model.
"""
import argparse
import importlib.util
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
from smoke_helpers import api, wait_idle, assert_findings_delivered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--authorize-current-model", action="store_true", required=True)
    parser.add_argument("--resume-artifacts", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = args.resume_artifacts or Path(tempfile.mkdtemp(prefix="cc-thingz-review-active.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)

    def save(name, data):
        (run / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")

    subprocess.run(["opencode", "service", "status"], check=True, capture_output=True, timeout=30)
    sid = None
    work = run / "workspace with spaces"
    bundle = run / "bundle with spaces"
    progress = run / "progress.txt"
    plan = work / "docs/plans/review-smoke.md"
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

    def git(*argv):
        return subprocess.check_output(["git", *argv], cwd=work, env=env, text=True)

    try:
        if not args.resume_artifacts:
            parent = api("GET", f"/api/session/{args.parent}")["data"]
            model = parent["model"]
            assert model == {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "medium"}, model
            save("authorization", {"parentID": args.parent, "model": model, "parent_location": parent["location"]})
            for directory in ("plugins", "scripts"):
                shutil.copytree(root / directory, bundle / directory)
            (work / ".opencode/skills").mkdir(parents=True)
            (work / ".opencode/skills/exec").symlink_to(bundle / "plugins/planning/skills/exec")
            (work / "opencode.json").write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json", "snapshots": False,
                "skills": [str(work / ".opencode/skills")],
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            }) + "\n")
            plan.parent.mkdir(parents=True)
            plan.write_text("""# Addition review smoke
## Overview
add(a,b) returns the arithmetic sum for integers, including negatives and zero.
Only this tiny module/test/docs are in scope. No publications or pushes.
## Validation Commands
python3 -m unittest -v
### Task 1: Implement addition
- [x] Implement add and tests, document integer sum.
""")
            (work / "README.md").write_text("# Integer addition\n`counter.add(a,b)` returns the integer sum, including negatives and zero.\nRun `python3 -m unittest -v`.\n")
            (work / "counter.py").write_text('"""Integer arithmetic."""\n\ndef add(a, b):\n    return a - b\n')
            (work / "test_counter.py").write_text('import unittest\nfrom counter import add\n\nclass CounterTests(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n')
            git("init", "-qb", "main")
            git("config", "user.name", "Review smoke")
            git("config", "user.email", "review@example.invalid")
            git("add", ".opencode", "opencode.json")
            git("commit", "-qm", "fixture base")
            git("switch", "-qc", "review-smoke")
            git("add", "counter.py", "test_counter.py", "README.md", "docs/plans/review-smoke.md")
            git("commit", "-qm", "feat: integer sum")
            owned = git("rev-parse", "HEAD").strip()
            (work / "foreign.txt").write_text("keep staged\n")
            git("add", "foreign.txt")
            save("before", {"head": owned, "foreign_diff": git("diff", "--cached", "--binary")})
            scripts = bundle / "plugins/planning/skills/exec/scripts"
            subprocess.run(["bash", str(scripts / "init-progress.sh"), str(progress), str(plan), "review-smoke"], check=True)
            sid = api("POST", "/api/session", {"title": "Task9 real review phases", "agent": "build",
                "location": {"directory": str(work)}, "model": model,
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]})["data"]["id"]
            save("session", {"id": sid})
            deadline = time.monotonic() + 30
            while True:
                registry = api("GET", "/api/skill?" + urlencode({"location[directory]": str(work)}))["data"]
                skill = next((s for s in registry if s["id"] == "exec"), None)
                if skill and Path(skill["path"]).resolve() == bundle / "plugins/planning/skills/exec/SKILL.md":
                    break
                assert time.monotonic() < deadline, "project skill discovery timeout"
                time.sleep(.2)
            save("discovery", skill)
            api("POST", f"/api/session/{sid}/prompt", {"text":
                f"Load project exec skill from {bundle}. Execute ONLY review/completion phases 7–13 "
                f"for the ALREADY task-complete plan {plan}, in-place agreed, working directory {work}. "
                f"Progress initialized at {progress}; root session ID {sid}. No questions. "
                "Follow active review-phases.md and resolved templates/agents; ignore inactive legacy SKILL reference. "
                "Explicit authorized smoke settings: review_iterations=2, external_review_iterations=1, "
                "finalize_enabled=true, external_review_cmd empty (real Codex default, bounded timeout 45s). "
                "These are test-run settings data, do not read/change global user settings or overrides. "
                "No custom rules. Applicable instructions: preserve foreign.txt staged exactly, no push/publication, "
                "no global/config/service edits. Only fixture module/tests/docs are in scope. "
                f"Default branch main. Recorded owned commit {owned}; NO rewrite/fetch/squash authorization. "
                "Real main-orchestrator five parallel comprehensive reviewers, complete unfiltered outputs to fresh "
                "fixer if found, two parallel critical recheck on iteration2, one smells, real external helper, "
                "two parallel final critical, safe verify-only finalizer, actual API stats child, then sole move-plan. "
                "Do not implement/fix code as parent or tell reviewers what defect to find. "
                "Use fresh general children inheriting model; explicit workdir everywhere. "
                "Save all full findings in progress and preserve transcripts. Store API stats evidence under run. "
                "Run tests with PYTHONDONTWRITEBYTECODE=1 to avoid generated artifacts. "
                "Log [decision] if rewrite skipped for foreign staged state, report every deviation at completion."})
        else:
            sid = json.loads((run / "session.json").read_text())["id"]
            assert json.loads((run / "authorization.json").read_text())["parentID"] == args.parent, "resume authorization mismatch"
            assert sid != args.parent, "caller parent cannot be the smoke session"
        wait_idle(api, save, sid)
        context = api("GET", f"/api/session/{sid}/context")
        save("context", context)
        calls = [p for m in context["data"] for p in m.get("content", []) if p.get("type") == "tool"]
        child_calls = [c for c in calls if c["name"] == "subagent"]
        save("child-calls", child_calls)
        assert len(child_calls) == 13, "expected exactly the tiny fixture's 13 review/fixer/finalize/stats children"
        for c in child_calls:
            inp = c["state"]["input"]
            assert inp["agent"] == "general" and not inp.get("sessionID"), inp
            assert str(work) in inp["prompt"]
            assert c["state"]["status"] == "completed", c
        first = child_calls[:5]
        assert max(c["time"]["ran"] for c in first) < min(c["time"]["completed"] for c in first), "no real five-way overlap"
        fixer = child_calls[5]
        assert "fix" in fixer["state"]["input"]["description"].lower(), fixer
        assert min(fixer["time"]["ran"], fixer["time"]["created"]) >= max(c["time"]["completed"] for c in first)
        fixer_prompt = fixer["state"]["input"]["prompt"]
        fixer_context = api("GET", f'/api/session/{fixer["state"]["metadata"]["sessionID"]}/context')
        save("fixer-received-context", fixer_context)
        received_reads = "\n".join(p["text"] for m in fixer_context["data"] for c in m.get("content", [])
                                   if c.get("name") == "read" and c["state"]["status"] == "completed"
                                   for p in c["state"].get("content", []) if p.get("type") == "text")
        for c in first:
            output = assert_findings_delivered(c, fixer_prompt, received_reads)
            save("raw-" + c["id"], {"output": output})
        recheck = child_calls[6:8]
        assert max(c["time"]["ran"] for c in recheck) < min(c["time"]["completed"] for c in recheck), "critical recheck not parallel"
        assert min(c["time"]["ran"] for c in recheck) >= fixer["time"]["completed"]
        smells, final_critical = child_calls[8], child_calls[9:11]
        finalizer, stats_call = child_calls[11:13]
        assert "smell" in smells["state"]["input"]["description"].lower()
        assert all("critical" in c["state"]["input"]["description"].lower() for c in final_critical)
        assert "finaliz" in finalizer["state"]["input"]["description"].lower()
        assert "stats" in stats_call["state"]["input"]["description"].lower()
        assert smells["time"]["ran"] >= max(c["time"]["completed"] for c in recheck)
        assert min(c["time"]["ran"] for c in final_critical) >= smells["time"]["completed"]
        assert max(c["time"]["ran"] for c in final_critical) < min(c["time"]["completed"] for c in final_critical)
        assert finalizer["time"]["ran"] >= max(c["time"]["completed"] for c in final_critical)
        assert stats_call["time"]["ran"] >= finalizer["time"]["completed"]
        external_statuses = []
        for path in run.rglob("status.json"):
            status = json.loads(path.read_text())
            if "stdout_file" in status and "stderr_file" in status:
                external_statuses.append(status)
        assert len(external_statuses) == 1, "external iteration count differs from authorized one"
        external_status = external_statuses[0]
        descriptions = [c["state"]["input"]["description"] for c in child_calls]
        stats_calls = [c for c in child_calls if "stats" in c["state"]["input"]["description"].lower()]
        assert len(stats_calls) == 1, "missing/duplicated stats child"
        stats_output = "\n".join(p["text"] for p in stats_calls[0]["state"].get("content", []) if p.get("type") == "text")
        stats_output = re.sub(r'^<subagent[^>]*>\n|\n</subagent>$', '', stats_output)
        parent_text = "\n".join(p.get("text", "") for m in context["data"] for p in m.get("content", []) if p.get("type") == "text")
        assert stats_output and stats_output in parent_text, "stats output not shown verbatim"
        children = api("GET", "/api/session?" + urlencode({"parentID": sid, "limit": 100}))["data"]
        save("children", children)
        child_ids = [c["state"].get("metadata", {}).get("sessionID") for c in child_calls]
        assert None not in child_ids and len(set(child_ids)) == len(child_ids), "reused/missing child session"
        assert set(child_ids) == {c["id"] for c in children}, "child metadata/list mismatch"
        auth = json.loads((run / "authorization.json").read_text())
        for child in children:
            assert child["location"]["directory"] == str(work)
            assert child["model"] == auth["model"]
            data = api("GET", f'/api/session/{child["id"]}/context')
            save(child["id"] + "-context", data)
            nested = [p for m in data["data"] for p in m.get("content", []) if p.get("type") == "tool" and p.get("name") == "subagent"]
            assert not nested, "nested fanout"
        spec = importlib.util.spec_from_file_location("review", root / "plugins/planning/skills/exec/scripts/exec-review.py")
        review = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(review)
        usage = review.stats(sid)
        save("api-usage-evidence", usage)
        assert usage["coverage"] == "complete", usage["errors"]
        assert len(usage["sessions"]) == len(children) + 1
        assert all(isinstance(s["tokens"], dict) for s in usage["sessions"])
        subprocess.run(["python3", "-m", "unittest", "-v"], cwd=work,
                       env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, check=True)
        assert subprocess.check_output(["python3", "-c", "from counter import add; print(add(7,3))"], cwd=work,
                                      env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, text=True).strip() == "10"
        assert not plan.exists() and (plan.parent / "completed" / plan.name).exists()
        before = json.loads((run / "before.json").read_text())
        assert git("diff", "--cached", "--binary") == before["foreign_diff"]
        moves = [line for line in git("log", "--format=%s").splitlines() if line.startswith("docs: move completed plan")]
        assert len(moves) == 1
        assert api("GET", f"/api/session/{args.parent}")["data"]["location"] == auth["parent_location"]
        (run / "progress-evidence.txt").write_text(progress.read_text())
        (run / "git-evidence.txt").write_text(git("log", "--stat") + git("status", "--short"))
        save("results", {"sessionID": sid, "model": auth["model"], "children": len(children),
             "descriptions": descriptions, "five_way_overlap": True, "defect_fixed": True,
             "single_move_commit": True, "foreign_index_preserved": True, "api_usage": usage["coverage"],
             "external": external_status, "stats_verbatim": True, "phase_order_verified": True,
             "full_findings_delivery": "inline or actual completed full READ tool evidence"})
        print("PASS real fanout/fixer/recheck/completion (inspect external outcome separately)", flush=True)
    except Exception as exc:
        (run / "failure.txt").write_text(repr(exc) + "\n")
        if sid:
            save("failure-context", api("GET", f"/api/session/{sid}/context"))
        raise


if __name__ == "__main__":
    main()
