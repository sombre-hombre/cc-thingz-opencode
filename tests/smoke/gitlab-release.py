#!/usr/bin/env python3
"""Deterministic helper PREVIEW smoke, NOT a model/V2 UI or live GitLab test."""
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_tests", ROOT / "tests/test-release-tools.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
test = module.ReleaseTests()
test.setUp()
artifacts = Path(tempfile.mkdtemp(prefix="cc-thingz-release-preview.", dir="/tmp/opencode"))
try:
    (test.repo / "changelog.md").write_text("# Changes\n\n## Unreleased\n")
    test.git("add", "changelog.md")
    test.git("commit", "-qm", "docs: changelog")
    test.git("tag", "v1.2.3")
    test.commit("feat: add auth")
    test.commit("fix: local-only correction")
    # Explicitly local/unrefreshed tags; no fetch, no external project writes.
    test.pages = [[test.mr(7, "feat: add auth", "2999-01-01T00:00:00Z")],
                  [test.mr(101, "fix: fix timeout", "2999-01-01T00:00:00Z")]]
    before = {"head": test.git("rev-parse", "HEAD"), "tags": test.git("tag", "--list"),
              "status": test.git("status", "--porcelain"),
              "changelog": (test.repo / "changelog.md").read_text()}
    data, path, confirm = test.make_preview()
    test.assertEqual(data["version"], "v1.3.0")
    test.assertIn("!101 @user101", data["notes"])
    test.assertRegex(data["notes"], r"local-only correction [0-9a-f]{7}")
    test.assertEqual(data["notes"].count("- add auth "), 1)
    proposed = f"# Changes\n\n## {data['version']}\n\n{data['notes']}\n\n## Unreleased\n"
    (artifacts / "proposed-changelog.md").write_text(proposed)
    (artifacts / "preview.json").write_bytes(path.read_bytes())
    after = {"head": test.git("rev-parse", "HEAD"), "tags": test.git("tag", "--list"),
             "status": test.git("status", "--porcelain"),
             "changelog": (test.repo / "changelog.md").read_text()}
    test.assertEqual(before, after)
    test.assertTrue(all(c[0] == "GET" for c in test.calls))
    denied = test.helper("publish", str(path), "--confirm", "not-confirmed")
    test.assertNotEqual(denied.returncode, 0)
    test.assertEqual(denied.stdout, "")
    (artifacts / "confirmation-denied.stderr").write_text(denied.stderr)
    (artifacts / "results.json").write_text(json.dumps({
        "kind": "deterministic helper preview, not V2 model/live GitLab",
        "tags": "local/unrefreshed fixture", "preview": data, "before": before,
        "after": after, "http_calls": test.calls, "writes": 0,
        "confirmation_denied_exit": denied.returncode, "result": "passed"
    }, indent=2))
    print(artifacts)
finally:
    test.doCleanups()
