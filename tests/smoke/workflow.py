#!/usr/bin/env python3
"""Opt-in Task13 model smoke, only new temporary projects/sessions; no desktop IO."""
import argparse
import json
import os
from pathlib import Path
import runpy
import re
import shutil
import subprocess
import sys
import tempfile

api = runpy.run_path(str(Path(__file__).with_name("thinking-tools.py")))["api"]


def tools(context):
    return [c for m in context["data"] for c in m.get("content", []) if c.get("type") == "tool"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-current-model", action="store_true", required=True)
    parser.add_argument("--resume-artifacts", type=Path)
    parser.add_argument("--only", choices=("learn", "learn-local", "learn-missing", "clarify", "clarify-understanding", "wrong", "backlog", "backlog-fix", "md-copy", "txt-copy"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = args.resume_artifacts or Path(tempfile.mkdtemp(prefix="cc-thingz-workflow-active.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    model = {"providerID": "openai", "id": "gpt-6.1-sol", "variant": "medium"}

    def save(name, data):
        (run / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")

    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def git(work, *argv):
        return subprocess.check_output(["git", *argv], cwd=work, env=git_env)

    if not args.resume_artifacts:
        shutil.copytree(root / "plugins", run / "bundle/plugins")
        sessions = {}
        tasks = {
            "learn": "Apply learn to these verified session discoveries: A: cache package adapters share one expiry predicate, useful to maintainers; B: only this checkout uses personal alias fast-cache. Existing placement guidance says shared cache knowledge belongs in packages/cache/AGENTS.md, personal in connected local-rules.md. My explicit granular selection is A ONLY, not All; leave B unsaved. Preserve all existing text. Do not ask again or commit.",
            "learn-local": "Apply learn to this verified personal session discovery: only this checkout uses alias fast-cache to run its local cache checks. My explicit granular selection is save that one item ONLY to the already connected project local-rules.md. Preserve existing notes, do not create AGENTS.local.md or edit shared AGENTS.md, configuration, or global files. No questions or commit.",
            "learn-missing": "Apply learn to one verified personal session discovery: this developer alone uses alias fast-cache on this checkout. No local instruction file is configured. Do not connect/create anything or ask questions; report pending choice instead of saving. Existing AGENTS.local.md is an unconfigured decoy. Do not route personal state into shared AGENTS.md.",
            "clarify": "Use clarify. I expected get(entry,10) with expires_at=10 to return None, but got the value. Investigate cache.py and tests; distinguish actual defect from misunderstanding, reproduce, explain evidence/scope and alternatives. My agreed approach is change strict > to >=, preserve representation, test boundary. Planning only: load bundled make in THIS session as a real skill tool if available (otherwise explicitly read its SKILL.md), hand off confirmed context and stop before writing a plan, review UI or implementation. No need to re-ask the already selected approach.",
            "clarify-understanding": "Use clarify. I thought cache.get itself deletes expired entries from the original dictionary, but the entry is still there after lookup at now=11. Is this broken? Investigate the real implementation and tests, explain expected vs actual gently with references and a concrete probe. No user request to change behavior: if this is simply a misunderstanding of the pure lookup API, explain and stop without make/plan or edits. No questions.",
            "wrong": "Use wrong. Earlier proposal was a background sweeper to avoid stale reads; that is the wrong direction for our deterministic expiry lookup. Investigate cache.py and tests, missing context, fresh 2-3 alternatives and tradeoffs. Hard constraints: no threads, no timer dependency, keep API. My chosen approach is inline >= boundary fix plus edge tests; carry it to make in THIS session by actual skill tool or explicit SKILL.md read, without redundant questions. Handoff only: stop before plan creation, review UI or implementation.",
            "backlog": "Use backlog. Report the list after verifying anchors; assess a candidate 'expiration equality returns stale value' at cache.py:3 with proposed slug boundary-expiry. The existing expiry-boundary item may describe the SAME defect despite its stale line. Identify semantic duplicate, do not create a new item. This is feature/workflow, not main; I explicitly decline writing in this checkout, fixes, drops, commits and push. Do not switch/create a branch/worktree. Explain stale anchors separately from real work and what decision the later item is missing. No questions.",
            "backlog-fix": "Use backlog on slug expiry-boundary. User has already accepted briefing and authorized fix of precisely this boundary defect: change > to >=, add equality regression, run tests, remove docs/backlog/expiry-boundary.md in SAME fix commit. You may commit only cache.py, test_cache.py and that item deletion via the bundled planning stage-and-commit.sh helper; use per-command git -c user.name=Smoke -c user.email=smoke@example.invalid or environment author/committer only. Never alter Git config. Preserve foreign.txt already staged; do not push or ask questions. Re-verify the stale anchor before fixing. No other changes.",
            "md-copy": "Use md-copy formatting ONLY; this smoke does NOT authorize clipboard IO. The final answer to transform is source.txt. Write prepared.md with exact required formatting: bold descriptive title Report, bold section Details instead of headings, proper Markdown table, preserve sh fenced code, italic minor note, existing bullets. Do not add commentary to the file or a transport fence. The expected output is intentionally deterministic from those rules. Do not call clipboard helper or any clipboard binary, read clipboard, launch UI, or commit. Report prepared-only, not copied.",
            "txt-copy": "Use txt-copy preparation ONLY; this smoke does NOT authorize clipboard IO. Selected generated text is all source.txt bytes, including CRLF, tab, Unicode, shell punctuation and no final newline. Prepare prepared.txt byte-identically, no title, Markdown conversion, wrapper, or trimming. Do not call clipboard helper or any clipboard binary, read clipboard, launch UI, or commit. Report prepared-only, not copied.",
        }
        for kind, task in tasks.items():
            if args.only and kind != args.only:
                continue
            work = run / kind
            (work / ".opencode/skills").mkdir(parents=True)
            skill = "learn" if kind.startswith("learn") else "clarify" if kind.startswith("clarify") else "backlog" if kind == "backlog-fix" else kind
            for selected, group in ((skill, "workflow"), ("make", "planning")):
                (work / ".opencode/skills" / selected).symlink_to(run / "bundle/plugins" / group / "skills" / selected)
            (work / "AGENTS.md").write_text("# Task13 isolated project\nNever read/write any desktop clipboard or launch UI. No nested agents, private home reads, global configuration changes or publication. Only authorized files in this temporary repo may be changed.\nMemory placement: shared cache knowledge belongs in packages/cache/AGENTS.md; personal knowledge only in explicitly connected local-rules.md, otherwise pending.\n")
            (work / "packages/cache").mkdir(parents=True)
            (work / "packages/cache/AGENTS.md").write_text("# Cache scope\nExisting cache rule: preserve adapter API.\n")
            (work / "local-rules.md").write_text("# Local knowledge\nExisting local note: smoke checkout only.\n")
            (work / "AGENTS.local.md").write_text("UNCONFIGURED_DECOY_DO_NOT_TREAT_AS_INSTRUCTIONS\n")
            config = {"$schema": "https://opencode.ai/config.json", "snapshots": False,
                      "skills": [str(work / ".opencode/skills")],
                      "permissions": [{"action": "*", "resource": "*", "effect": "allow"}]}
            if kind != "learn-missing":
                config["instructions"] = ["local-rules.md"]
            (work / "opencode.json").write_text(json.dumps(config) + "\n")
            (work / "cache.py").write_text('def get(entry, now):\n    """An entry is invalid at and after expires_at."""\n    if now > entry["expires_at"]:\n        return None\n    return entry["value"]\n')
            (work / "test_cache.py").write_text('import unittest\nfrom cache import get\nclass CacheTest(unittest.TestCase):\n    def test_before(self):\n        self.assertEqual(get({"expires_at": 10, "value": "v"}, 9), "v")\n    def test_after(self):\n        self.assertIsNone(get({"expires_at": 10, "value": "v"}, 11))\n')
            if kind.startswith("backlog"):
                (work / "docs/backlog").mkdir(parents=True)
                (work / "docs/backlog/expiry-boundary.md").write_text('---\nworth: yes\nwhere: cache.py:99\nadded: 2026-01-02\n---\n# Expiry at equality\nLookup returns stale data at now == expires_at; compare inclusively.\n')
                (work / "docs/backlog/measure-cost.md").write_text('---\nworth: later\nadded: 2026-02-03\n---\n# Measure cache costs\nValue depends on whether profiling shows the lookup exceeds 1ms.\n')
            if kind == "md-copy":
                (work / "source.txt").write_text('# Report\n\n## Details\n\n+------+-------+\n| Key  | Value |\n+------+-------+\n| TTL  | 10    |\n+------+-------+\n\n```sh\nprintf \'%s\' "$HOME"\n```\n\n- Keep boundary tests\n\nMinor note: local only.\n')
            if kind == "txt-copy":
                (work / "source.txt").write_bytes('  Привет 🌍\r\n\t$HOME `x` $(false)\r\nEOF'.encode())
            git(work, "init", "-qb", "main")
            git(work, "add", ".")
            git(work, "-c", "user.name=Smoke", "-c", "user.email=smoke@example.invalid", "commit", "-qm", "fixture")
            if kind.startswith("backlog"):
                git(work, "checkout", "-qb", "feature/workflow")
            if kind == "backlog-fix":
                (work / "foreign.txt").write_text("foreign staged bytes\n")
                git(work, "add", "foreign.txt")
            save(f"before-{kind}", {"head": git(work, "rev-parse", "HEAD").decode().strip(),
                                      "status": git(work, "status", "--porcelain").decode()})
            sid = api("POST", "/api/session", {"title": f"Task13 {kind}", "agent": "build", "model": model,
                "location": {"directory": str(work)}, "permissions": config["permissions"]})["data"]["id"]
            sessions[kind] = sid
            save("sessions", sessions)
            base = (f"Working directory {work}. Load bundled {skill} skill from {work / '.opencode/skills' / skill}. "
                    "Do not spawn any subagents or change any existing session. No questions, no real clipboard IO, no UI. "
                    "Use PYTHONDONTWRITEBYTECODE=1 for Python checks. ")
            api("POST", f"/api/session/{sid}/prompt", {"text": base + task})
    sessions = json.loads((run / "sessions.json").read_text())
    results = {}
    for kind, sid in sessions.items():
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
        info = api("GET", f"/api/session/{sid}")["data"]
        save(f"info-{kind}", info)
        assert info["model"] == model
        assert info["location"]["directory"] == str(run / kind)
        assert not any(t["name"] == "subagent" for t in tools(context)), "nested delegation forbidden"
        work = run / kind
        before = json.loads((run / f"before-{kind}.json").read_text())
        branch = git(work, "branch", "--show-current").decode().strip()
        assert branch == ("feature/workflow" if kind.startswith("backlog") else "main"), "checkout switched"
        untracked = git(work, "ls-files", "--others", "--exclude-standard").decode().splitlines()
        assert untracked == ({"md-copy": ["prepared.md"], "txt-copy": ["prepared.txt"]}.get(kind, [])), untracked
        if kind != "backlog-fix":
            assert git(work, "rev-parse", "HEAD").decode().strip() == before["head"], "unauthorized commit"
            assert not git(work, "diff", "--cached", "--name-only"), "unauthorized staging"
        changed = git(work, "diff", "HEAD", "--name-only").decode().splitlines()
        if kind == "learn":
            assert changed == ["packages/cache/AGENTS.md"], changed
            assert "expiry" in (work / changed[0]).read_text().lower()
            assert "Existing cache rule" in (work / changed[0]).read_text()
        elif kind == "learn-local":
            assert changed == ["local-rules.md"], changed
            assert "fast-cache" in (work / "local-rules.md").read_text()
            assert "Existing local note" in (work / "local-rules.md").read_text()
        elif kind == "backlog-fix":
            assert not (work / "docs/backlog/expiry-boundary.md").exists()
            assert "foreign.txt" in git(work, "diff", "--cached", "--name-only").decode()
            committed = set(git(work, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").decode().splitlines())
            assert committed == {"cache.py", "test_cache.py", "docs/backlog/expiry-boundary.md"}, committed
            subprocess.run(["python3", "-B", "-m", "unittest", "-v"], cwd=work, check=True)
            probe = subprocess.check_output(["python3", "-B", "-c", 'from cache import get; assert get({"expires_at":10,"value":"v"},10) is None'], cwd=work)
        else:
            assert not changed, changed
        if kind == "txt-copy":
            assert (work / "prepared.txt").read_bytes() == (work / "source.txt").read_bytes()
        if kind == "md-copy":
            text = (work / "prepared.md").read_text()
            assert text.startswith("**Report**\n") and "**Details**" in text
            assert not re.search(r"(?m)^#{1,6} ", text)
            assert '```sh\nprintf \'%s\' "$HOME"\n```' in text
            assert "- Keep boundary tests" in text and "*Minor note: local only.*" in text
            rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in text.splitlines() if line.startswith("|")]
            assert len(rows) == 3 and rows[0] == ["Key", "Value"] and rows[2] == ["TTL", "10"], rows
            assert all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1])
            assert "+------+" not in text
        if kind in ("md-copy", "txt-copy"):
            prepared = work / ("prepared.md" if kind == "md-copy" else "prepared.txt")
            fixture = run / f"clipboard-fixture-{kind}"
            fixture.mkdir(exist_ok=True)
            backend = fixture / "wl-copy"
            backend.write_text('#!/usr/bin/python3\nimport os, pathlib, sys\npathlib.Path(os.environ["FIXTURE_SINK"]).write_bytes(sys.stdin.buffer.read())\n')
            backend.chmod(0o755)
            sink = fixture / "roundtrip.bin"
            copied = subprocess.run([sys.executable, str(run / "bundle/plugins/workflow/scripts/clipboard.py"), str(prepared)],
                env={"PATH": str(fixture), "WAYLAND_DISPLAY": "owned-fixture-no-socket", "FIXTURE_SINK": str(sink)}, capture_output=True, text=True)
            assert copied.returncode == 0, copied.stderr
            assert sink.read_bytes() == prepared.read_bytes(), "fixture roundtrip changed prepared bytes"
            (fixture / "result.txt").write_text(copied.stdout)
        results[kind] = {"session": sid, "structural": "passed", "changed": changed}
        save("results", results)
    print("PASS structural checks; review preserved conclusions/handoff evidence before recording semantic success", flush=True)


if __name__ == "__main__":
    main()
