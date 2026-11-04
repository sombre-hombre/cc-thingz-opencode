#!/usr/bin/env python3
"""Opt-in real installed-server contracts, not a model smoke without --live.

Pass the actual 2.1.1 binary, not a version-manager wrapper. Own server only;
no user config, credentials, shared-service lifecycle, or visible terminal UI.
"""
import argparse
import base64
import json
import importlib.util
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--plan-review", action="store_true", help="also test Task5 launcher in owned PTYs")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-v2-contracts.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(run)}
    for key, name in [("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                      ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"),
                      ("XDG_CACHE_HOME", "cache")]:
        (run / name).mkdir()
        env[key] = str(run / name)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTHOR_NAME="Contract", GIT_AUTHOR_EMAIL="contract@example.invalid",
               GIT_COMMITTER_NAME="Contract", GIT_COMMITTER_EMAIL="contract@example.invalid")
    work = run / "workspace with spaces"
    work.mkdir()
    bundle = run / "bundle with spaces"
    bundle.mkdir()
    for name in ["plugins", "commands"]:
        shutil.copytree(root / name, bundle / name)
    manifest = json.loads((root / "install-manifest.json").read_text())
    config = run / "config/opencode"
    for group in ["skills", "agents", "commands"]:
        for entry in manifest[group]:
            target = config / entry["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(bundle / entry["source"])
    def git(*argv, cwd=work):
        return subprocess.check_output(["git", *argv], cwd=cwd, env=env, text=True).strip()
    git("init", "-q", "-b", "main")
    (work / "fixture.txt").write_text("main\n")
    git("add", "fixture.txt")
    git("commit", "-qm", "main")
    git("checkout", "-qb", "feature")
    (work / "fixture.txt").write_text("feature source\n")
    git("commit", "-qam", "feature")
    original_head = git("rev-parse", "HEAD")
    source = run / "secondary source with spaces"
    git("worktree", "add", "-q", "-b", "secondary", str(source), "HEAD")
    (source / "fixture.txt").write_text("secondary source differs from canonical\n")
    git("commit", "-qam", "secondary", cwd=source)
    source_head = git("rev-parse", "HEAD", cwd=source)
    assert source_head != original_head
    (work / "dirty.txt").write_text("leave source unchanged\n")
    original_status = git("status", "--porcelain")
    # A test-only plugin records actual registered tools and outgoing schemas.
    # It neither supplies model responses nor changes workflow behavior.
    plugin = work / ".opencode/plugins/contracts"
    plugin.mkdir(parents=True)
    shutil.copy(root / "tests/smoke/v2-contract-plugin.js", plugin / "index.js")
    (plugin / "package.json").write_text(json.dumps({"name": "contract-probe", "type": "module",
                                                       "exports": {".": "./index.js"}}))
    (work / ".git/info/exclude").write_text("tool-schemas.json\nrequest-tool-schemas.json\nrequest-system.json\npermission-results.json\n")
    original_status = git("status", "--porcelain")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (run / "server-stderr.log").open("w") as stderr:
        proc = subprocess.Popen([str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                cwd=work, env={**env, "KITTY_LISTEN_ON": "unix:/nonexistent-contract-kitty",
                                    "KITTY_WINDOW_ID": "999999", "TMUX": "/nonexistent-contract-tmux,1,0"},
                                stdout=subprocess.PIPE, stderr=stderr)
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
                    raise RuntimeError("isolated server exited during startup")
            if not password:
                raise RuntimeError("isolated server startup timed out")
            auth = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()
            def api(method, path, body=None):
                request = urllib.request.Request(f"http://127.0.0.1:{port}" + path, method=method,
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                    data=None if body is None else json.dumps(body).encode())
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = response.read()
                    return json.loads(data) if data else None
            def save(name, data):
                (run / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")
            info = api("GET", "/api/info")
            assert info["version"] == "2.1.1", info["version"]
            save("openapi", api("GET", "/openapi.json"))
            # Registry activation is asynchronous on a freshly booted Location.
            deadline = time.monotonic() + 15
            while True:
                registries = {key: api("GET", "/api/" + key)["data"] for key in ["skill", "agent", "command"]}
                if any(e["id"] == "release" for e in registries["skill"]) or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
            save("registries", registries)
            expected = {e["id"] for e in manifest["skills"]}
            assert expected <= {e["id"] for e in registries["skill"]}, "missing symlink skills"
            assert {"plan-review", "external-plan-review", "plan"} <= {e["id"] for e in registries["agent"]}
            assert expected <= {e["name"] for e in registries["command"]}
            def effect(agent, action, resource):
                import fnmatch
                matches = [r["effect"] for r in agent["permissions"]
                           if fnmatch.fnmatchcase(action, r["action"]) and fnmatch.fnmatchcase(resource, r["resource"])]
                return matches[-1] if matches else "ask"
            for aid in ["plan-review", "external-plan-review"]:
                agent = next(e for e in registries["agent"] if e["id"] == aid)
                assert agent["mode"] == "subagent" and agent["color"] == "#00bcd4" and "model" not in agent
                assert effect(agent, "edit", "fixture.txt") == "deny"
                assert effect(agent, "shell", "touch fixture.txt") == "ask"
            external = next(e for e in registries["agent"] if e["id"] == "external-plan-review")
            assert effect(external, "edit", "/tmp/opencode/external-plan-review-unique/prompt.txt") == "allow"
            plan_agent = next(e for e in registries["agent"] if e["id"] == "plan")
            assert effect(plan_agent, "edit", "docs/plans/normal.md") == "deny"
            assert effect(plan_agent, "edit", str(run / "home/.opencode/plan/test.md")) == "allow"
            session = api("POST", "/api/session", {"title": "Task3 contract probe",
                "location": {"directory": str(work)}, "model": {"providerID": "opencode", "id": "big-pickle"}})["data"]
            sid = session["id"]
            api("POST", f"/api/experimental/session/{sid}/skill", {"id": "release", "resume": False})
            context = api("GET", f"/api/session/{sid}/context")
            save("skill-context", context)
            assert any(e.get("type") == "skill" and e.get("skill") == "release" for e in context["data"])
            release = next(e for e in registries["skill"] if e["id"] == "release")
            assert Path(release["path"]).resolve() == bundle / "plugins/release-tools/skills/release/SKILL.md"
            # Command evaluation uses the real server. No model is claimed here:
            # a deliberately absent model stops execution after durable admission.
            api("POST", f"/api/session/{sid}/model", {"model": {"providerID": "missing", "id": "missing"}})
            arguments = '"docs/plans/a plan.md" keep  two spaces $(touch MUST_NOT_EXIST)'
            api("POST", f"/api/session/{sid}/command", {"name": "make", "text": arguments})
            time.sleep(1)
            context = api("GET", f"/api/session/{sid}/context")
            save("command-context", context)
            assert arguments in json.dumps(context, ensure_ascii=False).replace('\\"', '"')
            assert any(m.get("type") == "idle" and m.get("error", {}).get("type") == "provider.no-route" for m in context["data"])
            assert not (work / "MUST_NOT_EXIST").exists()
            permissions = json.loads((work / "permission-results.json").read_text())
            assert len(permissions) == 4 and all(p["actual"] == p["expected"] for p in permissions)
            save("permission-results", permissions)
            # Explicit source HEAD and session move, all in a throw-away repository.
            api("POST", "/api/session", {"title": "Register secondary checkout", "location": {"directory": str(source)}})
            wt = api("POST", "/api/worktree", {"projectID": session["projectID"], "from": str(source),
                "directory": str(run / "worktrees"), "name": "probe"})
            save("worktree", wt)
            destination = Path(wt.get("data", wt)["directory"])
            assert git("rev-parse", "HEAD", cwd=destination) == source_head
            api("POST", f"/api/session/{sid}/move", {"directory": str(destination)})
            moved = api("GET", f"/api/session/{sid}")
            save("moved-session", moved)
            assert str(destination) in json.dumps(moved)
            api("POST", f"/api/session/{sid}/shell", {"command": "pwd"})
            moved_shell = api("GET", f"/api/session/{sid}/context")
            save("moved-shell", moved_shell)
            assert any(e.get("type") == "shell" and str(destination) in e.get("output", {}).get("output", "") for e in moved_shell["data"])
            assert git("rev-parse", "HEAD") == original_head and git("status", "--porcelain") == original_status
            spec = importlib.util.spec_from_file_location("terminal_probe", root / "tests/smoke/v2-terminal.py")
            terminal_probe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(terminal_probe)
            save("terminal-result", terminal_probe.probe(api, sid, run, env))
            if args.plan_review:
                spec = importlib.util.spec_from_file_location("plan_probe", root / "tests/smoke/plan-review-pty.py")
                plan_probe = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plan_probe)
                save("task5-result", plan_probe.probe(api, sid, run, env, live=args.live))
            print("PASS real server discovery, skill activation, command admission, worktree source and move", flush=True)
            if args.live:
                live = api("POST", "/api/session", {"title": "Task3 live smoke", "location": {"directory": str(work)},
                    "model": {"providerID": "opencode", "id": "big-pickle"}})["data"]
                lid = live["id"]
                api("POST", f"/api/session/{lid}/command", {"name": "writing-style", "text":
                    'Packaging smoke only: load the skill, do not edit files. Reply with the exact path "docs/a plan.md".'})
                api("POST", f"/api/experimental/session/{lid}/wait", {})
                transcript = api("GET", f"/api/session/{lid}/context")
                save("live-command", transcript)
                calls = [part for msg in transcript["data"] for part in msg.get("content", []) if part.get("type") == "tool"]
                loaded = [part for part in calls if part["name"] == "skill" and part["state"].get("input") == {"id": "writing-style"}]
                assert loaded and loaded[0]["state"]["status"] == "completed", "no real slash-to-skill tool result"
                assert Path(loaded[0]["state"]["metadata"]["directory"]).resolve() == bundle / "plugins/review/skills/writing-style"
                assert any(p.get("type") == "text" and p["text"].strip().strip('`') == "docs/a plan.md" for m in transcript["data"] for p in m.get("content", []))
                # Composer @ is represented by a skill attachment + mention offsets.
                mention_session = api("POST", "/api/session", {"title": "Fresh composer mention probe", "location": {"directory": str(work)},
                    "model": {"providerID": "opencode", "id": "big-pickle"}})["data"]
                mid = mention_session["id"]
                mention = "@writing-style"
                prompt = mention + ' Packaging smoke: reply only "docs/another plan.md"; no file changes.'
                api("POST", f"/api/session/{mid}/prompt", {"text": prompt,
                    "skills": [{"id": "writing-style", "mention": {"start": 0, "end": len(mention), "text": mention}}]})
                api("POST", f"/api/experimental/session/{mid}/wait", {})
                mentioned = api("GET", f"/api/session/{mid}/context")
                save("live-mention", mentioned)
                assert any(m.get("type") == "user" and m.get("skills", []) for m in mentioned["data"])
                assert any(p.get("type") == "text" and p["text"].strip().strip('`') == "docs/another plan.md" for m in mentioned["data"] for p in m.get("content", []))
                schemas = json.loads((work / "request-tool-schemas.json").read_text())
                assert schemas["skill"]["input"]["required"] == ["id"]
                assert schemas["subagent"]["input"]["required"] == ["agent", "description", "prompt"]
                assert not {"task", "todowrite", "ExitPlanMode", "EnterPlanMode"} & schemas.keys()
                save("request-tool-schemas", schemas)
                native = api("POST", "/api/session", {"title": "Native Plan probe", "agent": "plan", "location": {"directory": str(work)},
                    "model": {"providerID": "opencode", "id": "big-pickle"}})["data"]
                native_file = run / "home/.opencode/plan/native-contract.md"
                api("POST", f"/api/session/{native['id']}/prompt", {"text":
                    f"Contract probe only. Use the write tool to create exactly {native_file} containing '# Native contract\\n'. "
                    "Do not create any other files or launch subagents. Then reply DONE."})
                api("POST", f"/api/experimental/session/{native['id']}/wait", {})
                save("native-plan", api("GET", f"/api/session/{native['id']}/context"))
                assert native_file.is_file() and native_file.read_text().startswith("# Native contract")
                assert git("status", "--porcelain") == original_status
                print("PASS real Big Pickle slash -> skill, base directory, composer mention and paths with spaces", flush=True)
            else:
                print("NOT RUN: real model @/slash-to-skill smoke (--live required)", flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
