#!/usr/bin/env python3
"""Opt-in installed V2 lifecycle smoke. Stops before provider I/O; not a model E2E."""
import base64
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    binary = Path(sys.argv[1]).resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-skill-eval-runtime.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    env = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "TMPDIR": str(run)}
    for key, name in [("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                      ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                      ("XDG_CACHE_HOME", "cache")]:
        (run / name).mkdir()
        env[key] = str(run / name)
    work = run / "workspace with spaces"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, env=env, check=True)
    plugins = work / ".opencode/plugins"
    package = plugins / "skill-eval"
    shutil.copytree(root / "integrations/opencode/skill-eval", package)
    sdk = Path("/tmp/opencode/cc-thingz-skill-eval-sdk/node_modules")
    (package / "node_modules").symlink_to(sdk)
    probe = plugins / "zz-probe"
    probe.mkdir()
    (probe / "package.json").write_text(json.dumps({"name": "skill-eval-probe", "type": "module", "exports": {".": "./index.js"}}))
    (probe / "index.js").write_text('''import { appendFile } from "node:fs/promises"
export default { id: "skill-eval-probe", async setup(ctx) {
  const save = (data) => appendFile(ctx.location.directory + "/probe.jsonl", JSON.stringify(data) + "\\n")
  await save({kind:"setup"})
  await ctx.session.hook("context", async e => {
    await save({kind:"context", sessionID:e.sessionID, system:e.system, messages:e.messages})
  })
  await ctx.session.hook("compaction", async e => {
    await save({kind:"compaction", sessionID:e.sessionID, system:e.system})
    e.result = { summary: "Fixture compaction; no model invoked." }
  })
  await ctx.session.hook("title", e => { e.result = "Skill eval fixture" })
  await ctx.session.hook("model.request", () => { throw new Error("SKILL_EVAL_STOP_BEFORE_NETWORK") })
  return () => save({kind:"cleanup"})
}}''')
    skill = work / ".opencode/skills/fixture/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: fixture\ndescription: Only the explicit fixture task.\n---\nReply fixture.\n')
    commands = work / ".opencode/commands"
    commands.mkdir()
    (commands / "fixture.md").write_text('---\ndescription: Fixture prompt\nsubagent: false\n---\nKeep exact: $ARGUMENTS\n')
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    stderr = (run / "server-stderr.log").open("w")
    proc = subprocess.Popen([str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                            cwd=work, env=env, stdout=subprocess.PIPE, stderr=stderr)
    try:
        startup = b""
        password = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not password:
            if select.select([proc.stdout], [], [], 1)[0]:
                startup += os.read(proc.stdout.fileno(), 65536)
                for line in startup.splitlines(keepends=True):
                    if line.startswith(b"server password ") and line.endswith(b"\n"):
                        password = line.decode().strip().removeprefix("server password ")
            if proc.poll() is not None:
                raise RuntimeError("isolated server exited")
        assert password, "startup timed out"
        auth = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()

        def api(method, path, body=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}" + path, method=method,
                headers={"Authorization": auth, "Content-Type": "application/json"},
                data=None if body is None else json.dumps(body).encode())
            with urllib.request.urlopen(req, timeout=45) as response:
                data = response.read()
                return json.loads(data) if data else None

        def wait(predicate):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.2)
            raise AssertionError("lifecycle wait timed out")

        def records():
            path = work / "probe.jsonl"
            return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []

        def contexts(sid):
            return [r for r in records() if r["kind"] == "context" and r["sessionID"] == sid]

        def count(r):
            return sum("INSTRUCTION: MANDATORY SKILL ACTIVATION" in p.get("text", "") for p in r["system"])

        def create(parent=None):
            body = {"title": "Skill eval runtime", "location": {"directory": str(work)},
                    "model": {"providerID": "opencode", "id": "big-pickle"}}
            if parent:
                body["parentID"] = parent
            return api("POST", "/api/session", body)["data"]["id"]

        def prompt(sid, text):
            before = len(contexts(sid))
            api("POST", f"/api/session/{sid}/prompt", {"text": text})
            wait(lambda: len(contexts(sid)) > before)
            # Wait for deliberate provider stop, not an in-flight request.
            wait(lambda: any(m.get("error", {}).get("message", "").find("SKILL_EVAL_STOP_BEFORE_NETWORK") >= 0
                             for m in api("GET", f"/api/session/{sid}/context")["data"]))

        assert api("GET", "/api/info")["version"] == "2.1.1"
        first = create()
        api("GET", "/api/skill")
        wait(lambda: any(r["kind"] == "setup" for r in records()))
        (run / "plugin-list.json").write_text(json.dumps(api("GET", "/api/plugin"), indent=2))
        prompt(first, "Ordinary no-match request; preserve  two spaces")
        assert count(contexts(first)[-1]) == 1
        persisted = api("GET", f"/api/session/{first}/context")["data"]
        user = next(m for m in persisted if m["type"] == "user")
        assert user["text"] == "Ordinary no-match request; preserve  two spaces"
        assert user["metadata"]["cc-thingz/skill-eval"] is True
        before = len(contexts(first))
        api("POST", f"/api/session/{first}/prompt", {"id": user["id"], "text": user["text"]})
        time.sleep(.5)
        assert len(contexts(first)) == before, "retry of delivered ID must not dispatch again"
        second = create()
        api("POST", f"/api/experimental/session/{second}/skill", {"id": "fixture", "resume": False})
        prompt(second, "Already-loaded fixture request")
        assert count(contexts(second)[-1]) == 1
        assert "current context: fixture." in json.dumps(contexts(second)[-1]["system"])
        api("POST", f"/api/session/{second}/compact", {})
        wait(lambda: any(r["kind"] == "compaction" for r in records()))
        compact = next(r for r in records() if r["kind"] == "compaction")
        assert count(compact) == 0
        prompt(second, "Use available fixture after compaction")
        assert "current context: fixture." in json.dumps(contexts(second)[-1]["system"])
        attached = create()
        file = work / "file with spaces.txt"
        file.write_text("Attachment bytes intact\n")
        text = "@fixture @file @general keep  two spaces"
        attachments = {"text": text, "skills": [{"id": "fixture", "mention": {"start": 0, "end": 8, "text": "@fixture"}}],
            "files": [{"uri": file.as_uri(), "mention": {"start": 9, "end": 14, "text": "@file"}}],
            "agents": [{"name": "general", "mention": {"start": 15, "end": 23, "text": "@general"}}]}
        api("POST", f"/api/session/{attached}/prompt", attachments)
        wait(lambda: bool(contexts(attached)))
        assert count(contexts(attached)[-1]) == 1
        assert "current context: fixture." in json.dumps(contexts(attached)[-1]["system"])
        attached_history = api("GET", f"/api/session/{attached}/context")
        (run / "attachment-context.json").write_text(json.dumps(attached_history, indent=2))
        attached_user = next(m for m in attached_history["data"] if m["type"] == "user")
        assert attached_user["text"] == text
        for group in ["skills", "files", "agents"]:
            assert attached_user[group][0]["mention"] == attachments[group][0]["mention"]
        assert base64.b64decode(attached_user["files"][0]["data"]) == file.read_bytes()
        before = len(contexts(first))
        api("POST", f"/api/session/{first}/command", {"name": "fixture", "text": '"a b"  $(literal)'})
        wait(lambda: len(contexts(first)) > before)
        assert count(contexts(first)[-1]) == 1
        before = len(contexts(first))
        api("POST", f"/api/session/{first}/synthetic", {"text": "Synthetic only"})
        wait(lambda: len(contexts(first)) > before)
        assert count(contexts(first)[-1]) == 0
        child = create(first)
        prompt(child, "Explicitly admitted child request")
        assert count(contexts(child)[-1]) == 1
        # Real watcher reload, without restarting any service.
        before = sum(r["kind"] == "setup" for r in records())
        path = package / "index.ts"
        path.write_text(path.read_text() + "\n// reload fixture\n")
        wait(lambda: sum(r["kind"] == "setup" for r in records()) > before)
        assert any(r["kind"] == "cleanup" for r in records())
        prompt(first, "New prompt after watcher reload")
        assert count(contexts(first)[-1]) == 1
        # Capture actual history for independent inspection; no tokens/model success claim.
        for name, sid in [("first", first), ("second", second), ("child", child)]:
            (run / f"{name}-context.json").write_text(json.dumps(api("GET", f"/api/session/{sid}/context"), indent=2))
        print("PASS installed load, watcher cleanup/reload, prompt/command/attachments/synthetic/compaction, loaded skill, child admission")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        stderr.close()


if __name__ == "__main__":
    main()
