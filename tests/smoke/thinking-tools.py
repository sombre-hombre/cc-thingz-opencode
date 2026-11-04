#!/usr/bin/env python3
"""Opt-in Task12 live model checks; new sessions only, no credentials/config copies."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def api(method, path, body=None):
    argv = ["opencode", "api", method.lower(), path]
    if body is not None:
        argv += ["--data", json.dumps(body)]
    with tempfile.TemporaryFile(mode="w+", dir="/tmp/opencode") as output:
        p = subprocess.run(argv, stdout=output, stderr=subprocess.PIPE, text=True, timeout=1800)
        if p.returncode:
            raise RuntimeError(p.stderr)
        output.seek(0)
        text = output.read()
        return json.loads(text) if text.strip() else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authorize-current-model", action="store_true", required=True)
    p.add_argument("--resume-artifacts", type=Path)
    p.add_argument("--only", choices=("dialectic", "root-cause-investigator", "ask-codex"))
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = args.resume_artifacts or Path(tempfile.mkdtemp(prefix="cc-thingz-thinking-active.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)

    def save(name, data):
        (run / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")

    model = {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "medium"}
    if not args.resume_artifacts:
        bundle = run / "bundle"
        shutil.copytree(root / "plugins", bundle / "plugins")
        sessions = {}
        kinds = (args.only,) if args.only else ("dialectic", "root-cause-investigator", "ask-codex")
        for kind in kinds:
            work = run / kind
            (work / ".opencode/skills").mkdir(parents=True)
            (work / ".opencode/skills" / kind).symlink_to(bundle / "plugins/thinking-tools/skills" / kind)
            (work / "AGENTS.md").write_text("# Scope: this test project\nRead-only investigation. No fixes, publications, global configuration changes, or credential reads.\n")
            (work / "local-rules.md").write_text("Review memo: expected TTL expiry is now >= expires_at. Preserve original evidence.\n")
            (work / "AGENTS.local.md").write_text("UNCONFIGURED_DECOY_DO_NOT_LOAD\n")
            (work / "opencode.json").write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json", "snapshots": False,
                "instructions": ["local-rules.md"], "skills": [str(work / ".opencode/skills")],
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            }) + "\n")
            (work / "cache.py").write_text('''"""Expiry cache. The value is invalid at and after expires_at."""
def get(entry, now):
    if now > entry["expires_at"]:
        return None
    return entry["value"]
''')
            (work / "test_cache.py").write_text('''import unittest
from cache import get
class CacheTest(unittest.TestCase):
    def test_before(self):
        self.assertEqual(get({"expires_at": 10, "value": "stale"}, 9), "stale")
    def test_after(self):
        self.assertIsNone(get({"expires_at": 10, "value": "stale"}, 11))
''')
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
            for command in (["git", "init", "-qb", "main"], ["git", "add", "."],
                            ["git", "-c", "user.name=Smoke", "-c", "user.email=smoke@example.invalid", "commit", "-qm", "fixture"]):
                subprocess.run(command, cwd=work, env=env, check=True, capture_output=True)
            sid = api("POST", "/api/session", {"title": f"Task12 {kind}", "agent": "build",
                "location": {"directory": str(work)}, "model": model,
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]})["data"]["id"]
            sessions[kind] = sid
        save("sessions", sessions)
        for kind, sid in sessions.items():
            work = run / kind
            base = (f"Load skill {kind} from the project skill directory {work / '.opencode/skills'}. "
                    f"Working directory {work}. Read-only authorized investigation, no questions or fixes. "
                    "Do not read/copy credentials or dump global config/environment. Use PYTHONDONTWRITEBYTECODE=1 for checks. ")
            task = {
                "dialectic": 'Stress test this claim: "The cache never returns expired values, and the current tests establish that guarantee." Analyze cache.py and test_cache.py; main orchestrator must launch exactly two fresh opposed general children concurrently, then itself verify their citations and counterexamples. No additional children.',
                "root-cause-investigator": "Investigate reported stale value at now=10 for an entry expiring at 10. Apply the full 5-Why evidence/impact format, load relevant bundled references, reproduce the behavior, distinguish supported causes from unknown history; no child agents.",
                "ask-codex": "Ask external Codex to investigate whether cache expiry matches its documented contract. Execute the actual bundled run-codex helper via shell background:true and completion notification, no polling. Bound wall time to 90 seconds for this smoke. Pass applicable project AGENTS.md and explicitly configured local-rules.md, not unconfigured AGENTS.local.md; no global private guidance export (record that gap). Save separate stdout/stderr/status under this project, preserve nonzero failure, show independent assessment and stop without fixes. Do not substitute your parent model for the external CLI. No children.",
            }[kind]
            api("POST", f"/api/session/{sid}/prompt", {"text": base + task})
    sessions = json.loads((run / "sessions.json").read_text())
    contexts = {}
    for kind, sid in sessions.items():
        # Native blocking wait, reconnect only transport failure, no status polling.
        for attempt in range(8):
            try:
                api("POST", f"/api/experimental/session/{sid}/wait", {})
                break
            except RuntimeError as exc:
                save(f"wait-failure-{kind}-{attempt}", {"error": str(exc)})
                if "TimeoutError" not in str(exc) or attempt == 7:
                    raise
        context = api("GET", f"/api/session/{sid}/context")
        save(f"context-{kind}", context)
        contexts[kind] = context
        assert api("GET", f"/api/session/{sid}")["data"]["model"] == model
        work = run / kind
        assert not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=work), "tracked evidence changed"
    def tools(ctx):
        return [c for m in ctx["data"] for c in m.get("content", []) if c.get("type") == "tool"]
    calls = [c for c in tools(contexts.get("dialectic", {"data": []})) if c["name"] == "subagent"]
    if "dialectic" in contexts:
        assert len(calls) == 2, "exactly two children required"
        assert max(c["time"]["ran"] for c in calls) < min(c["time"]["completed"] for c in calls), "no overlap"
    for n, c in enumerate(calls):
        assert c["state"]["input"]["agent"] == "general"
        assert not c["state"]["input"].get("sessionID"), "not fresh"
        assert str(run / "dialectic") in c["state"]["input"]["prompt"]
        child = api("GET", f'/api/session/{c["state"]["metadata"]["sessionID"]}/context')
        save(f"child-{n}", child)
        info = api("GET", f'/api/session/{c["state"]["metadata"]["sessionID"]}')["data"]
        save(f"child-info-{n}", info)
        assert info["model"] == model
        assert info["location"]["directory"] == str(run / "dialectic")
        assert not any(t["name"] == "subagent" for t in tools(child)), "nested fanout"
    for kind in ("ask-codex", "root-cause-investigator"):
        assert not any(t["name"] == "subagent" for t in tools(contexts.get(kind, {"data": []})))
    if "ask-codex" in contexts:
        tc = tools(contexts["ask-codex"])
        assert any(c["name"] == "shell" and c["state"]["input"].get("background") for c in tc), "Codex was not backgrounded"
        reads = [c["state"]["input"].get("path", "") for c in tc if c["name"] == "read"]
        if not any("stdout" in x or "codex.out" in x for x in reads):
            save("results", {"status": "PENDING external completion notification; not a passed Codex smoke", "sessions": sessions})
            print("PENDING external completion; resume validation only after notification", flush=True)
            raise SystemExit(2)
    save("results", {"status": "structural checks passed; substantive outputs require recorded evidence review", "sessions": sessions})
    print("PASS structural live checks; inspect preserved contexts for conclusions", flush=True)


if __name__ == "__main__":
    main()
