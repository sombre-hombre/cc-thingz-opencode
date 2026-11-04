#!/usr/bin/env python3
"""Loopback GitLab fixture + actual installed glab; no remote project or secrets."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugins/review/skills/pr/scripts/gitlab-context.py"
FIXTURE = json.loads((ROOT / "tests/fixtures/gitlab/context.json").read_text())
spec = importlib.util.spec_from_file_location("gitlab_context", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GitLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("glab"):
            raise RuntimeError("glab required: fixture CLI coverage is not a skipped success")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gitlab review ")
        self.addCleanup(self.tmp.cleanup)
        self.data = copy.deepcopy(FIXTURE)
        self.calls = []
        self.failure = None
        self.changed_head = False
        self.metadata_reads = 0
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path.removeprefix("/api/v4/")
                page = int(parse_qs(parsed.query).get("page", ["1"])[0])
                test.calls.append(("GET", path, page))
                path = path.replace("projects/team%2Fplatform%2Fservice/", "projects/73/", 1)
                if test.failure and test.failure[:2] == (path, page):
                    self.reply(test.failure[2], {"message": "fixture error"})
                    return
                if path == "projects/team%2Fplatform%2Fservice" or path == "projects/73":
                    self.reply(200, test.data["project"])
                elif path == "user":
                    self.reply(200, test.data["user"])
                elif path in {"projects/73/merge_requests/42", "projects/73/issues/42"}:
                    value = copy.deepcopy(test.data["mr" if "merge_requests" in path else "issue"])
                    test.metadata_reads += 1
                    if test.changed_head and test.metadata_reads > 1:
                        value["sha"] = "e" * 40
                    self.reply(200, value)
                elif path.startswith(("projects/73/merge_requests/42/", "projects/73/issues/42/")):
                    key = path.rsplit("/", 1)[1]
                    value = test.data.get(key)
                    if value is None:
                        self.reply(404, {"message": "unexpected route"})
                    elif isinstance(value, list):
                        pages = value
                        headers = {}
                        if page < len(pages):
                            next_url = f"http://{test.api_host}/api/v4/{path}?page={page+1}&per_page=100"
                            headers = {"Link": f'<{next_url}>; rel="next"', "X-Next-Page": str(page+1)}
                        self.reply(200, pages[page-1] if page <= len(pages) else [], headers)
                    else:
                        self.reply(200, value)
                else:
                    self.reply(404, {"message": "unexpected route"})

            def do_POST(self):
                self.write_fixture()

            def do_PUT(self):
                self.write_fixture()

            def write_fixture(self):
                # A local contract sink ONLY; never a real GitLab write.
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                test.calls.append((self.command, self.path, body))
                if test.failure:
                    self.reply(test.failure[2], {"message": "fixture write denied"})
                else:
                    self.reply(201 if self.command == "POST" else 200, {"id": 123, **body})

            def reply(self, code, value, headers=None):
                payload = json.dumps(value).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for key, val in (headers or {}).items():
                    self.send_header(key, val)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api_host = f"127.0.0.1:{self.server.server_port}"
        self.host = "gitlab.fixture.test"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        # Explicit throwaway environment; not user credentials/config/keyring.
        self.env = {"PATH": os.environ["PATH"], "HOME": self.tmp.name,
                    "XDG_CONFIG_HOME": self.tmp.name, "GLAB_CONFIG_DIR": self.tmp.name,
                    "GITLAB_HOST": self.host, "GITLAB_API_HOST": self.api_host,
                    "GITLAB_TOKEN": "fixture-only-not-a-secret",
                    "GLAB_API_PROTOCOL": "http", "GLAB_CHECK_UPDATE": "false",
                    "GLAB_SEND_TELEMETRY": "false", "NO_COLOR": "1",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

    def run_context(self, kind="mr", extra=(), helper=HELPER):
        return subprocess.run(["python3", str(helper), "--host", self.host,
                               "--project", "team/platform/service", "--kind", kind,
                               "--iid", "42", *extra], env=self.env, cwd=self.tmp.name,
                              capture_output=True, text=True, timeout=30)

    def test_real_cli_pagination_nested_namespace_and_identity(self):
        result = self.run_context()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["metadata"]["id"], 9001)
        self.assertEqual(data["iid"], 42)
        self.assertIn(("GET", "projects/team%2Fplatform%2Fservice", 1), self.calls)
        self.assertEqual([n["id"] for n in data["notes"]], [101, 102])
        self.assertEqual([c["title"] for c in data["commits"]], ["wip", "fix lint"])
        self.assertTrue(data["diffs"][1]["too_large"])
        self.assertEqual(data["metadata"]["changes_count"], "1000+")
        note = data["discussions"][1]["notes"][0]
        self.assertEqual(note["suggestions"][0]["id"], 66)
        self.assertEqual(note["position"]["new_line"], 27)
        self.assertFalse(note["resolved"])
        self.assertTrue(data["discussions"][0]["notes"][0]["resolved"])
        self.assertFalse(data["approvals"]["data"]["user_can_approve"])
        self.assertNotIn("approvals_left", data["approvals"]["data"])
        self.assertEqual(data["pipelines"][0]["project_id"], 88)
        self.assertEqual(data["metadata"]["detailed_merge_status"], "ci_still_running")
        self.assertTrue(all(call[0] == "GET" and "9001" not in call[1] for call in self.calls))

    def test_same_iid_issue_skips_mr_endpoints(self):
        result = self.run_context("issue")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["metadata"]["id"], 8002)
        self.assertEqual(len(data["discussions"]), 2)
        self.assertFalse(any("merge_requests" in c[1] for c in self.calls))

    def test_required_errors_and_later_page_never_emit_partial_snapshot(self):
        for path, page, status in [("user", 1, 401), ("projects/73/merge_requests/42", 1, 404),
                                   ("projects/73/merge_requests/42/notes", 1, 403),
                                   ("projects/73/merge_requests/42/discussions", 2, 500),
                                   ("projects/73/merge_requests/42/discussions", 2, 429)]:
            with self.subTest(path=path, page=page, status=status):
                self.calls.clear()
                self.failure = (path, page, status)
                result = self.run_context()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn(str(status), result.stderr)
                self.assertFalse(any("issues" in c[1] for c in self.calls))

    def test_optional_approval_rights_unavailable_not_approved(self):
        for status in (403, 404):
            self.failure = ("projects/73/merge_requests/42/approval_state", 1, status)
            result = self.run_context()
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(result.stdout)["approval_state"]
            self.assertEqual(state["http_status"], status)
            self.assertFalse(state["available"])
            self.assertNotIn("data", state)
        self.failure = ("projects/73/merge_requests/42/approvals", 1, 401)
        self.assertNotEqual(self.run_context().returncode, 0)

    def test_changed_head_and_wrong_iid_fail(self):
        self.changed_head = True
        result = self.run_context()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed", result.stderr)
        self.changed_head = False
        self.data["mr"]["iid"] = 9001
        result = self.run_context()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatch", result.stderr)

    def test_symlink_helper_and_input_guards(self):
        link = Path(self.tmp.name) / "linked helper.py"
        link.symlink_to(HELPER)
        result = self.run_context(helper=link)
        self.assertEqual(result.returncode, 0, result.stderr)
        for extra in [("--host", "https://wrong.test"), ("--project", "team%2Frepo"),
                      ("--project", "team/../repo"), ("--iid", "0")]:
            self.calls.clear()
            result = self.run_context(extra=extra)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(self.calls, [])

    def test_malformed_timeout_missing_cli(self):
        for output in ("not json", "[]", "null"):
            with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                with self.assertRaises(module.ContextError):
                    module.api("example.test", "user")
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "[]\n", "")):
            with self.assertRaises(module.ContextError):
                module.api("example.test", "list", many=True)
        self.env["PATH"] = "/nonexistent"
        # Python is invoked absolutely for missing glab negative case.
        result = subprocess.run([shutil.which("python3"), str(HELPER), "--host", self.host,
                                 "--project", "73", "--kind", "mr", "--iid", "42"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("glab", result.stderr)
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("glab", 120)):
            with self.assertRaises(subprocess.TimeoutExpired):
                module.api("example.test", "user")

    def test_actual_glab_json_write_contract_to_loopback_only(self):
        body = {"body": 'quote " and newline\n```suggestion\nreturn checked(err)\n```'}
        path = Path(self.tmp.name) / "note body.json"
        for target in ("issues/42/notes", "merge_requests/42/notes", "merge_requests/42/discussions"):
            path.write_text(json.dumps(body))
            result = subprocess.run(["glab", "api", "--hostname", self.host, "--method", "POST",
                                     f"projects/73/{target}", "--input", str(path)], env=self.env,
                                    cwd=self.tmp.name, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls[-1][2], body)
        position = {"body": "fix here", "position": {"position_type": "text", "new_line": 27,
                    "old_path": "old file.py", "new_path": "new file.py", **self.data["mr"]["diff_refs"]}}
        path.write_text(json.dumps(position))
        result = subprocess.run(["glab", "api", "--hostname", self.host, "--method", "POST",
                                 "projects/73/merge_requests/42/discussions", "--input", str(path)],
                                env=self.env, cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls[-1][2], position)
        self.failure = ("unused", 1, 403)
        result = subprocess.run(["glab", "api", "--hostname", self.host, "--method", "POST",
                                 "projects/73/merge_requests/42/approve", "--input", str(path)],
                                env=self.env, cwd=self.tmp.name, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("403", result.stderr)

    def test_actual_approve_and_cli_false_caveat_then_exact_api_merge(self):
        repo = f"https://{self.host}/team/platform/service"
        result = subprocess.run(["glab", "mr", "approve", "42", "--repo", repo,
                                 "--sha", "a" * 40], env=self.env, cwd=self.tmp.name,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, (result.stderr, self.calls))
        writes = [c for c in self.calls if c[0] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertIn(writes[0][1], ["/api/v4/projects/73/merge_requests/42/approve",
                                   "/api/v4/projects/team%2Fplatform%2Fservice/merge_requests/42/approve"])
        self.assertEqual(writes[0][2]["sha"], "a" * 40)
        self.calls.clear()
        self.data["mr"]["user"] = {"can_merge": True}
        result = subprocess.run(["glab", "mr", "merge", "42", "--repo", repo,
                                 "--sha", "a" * 40, "--auto-merge=false", "--squash=false",
                                 "--remove-source-branch=false", "--yes"], env=self.env,
                                cwd=self.tmp.name, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = [c for c in self.calls if c[0] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertIn(writes[0][1], ["/api/v4/projects/73/merge_requests/42/merge",
                                   "/api/v4/projects/team%2Fplatform%2Fservice/merge_requests/42/merge"])
        self.assertEqual(writes[0][2]["sha"], "a" * 40)
        # Installed 1.124's false flags are omitted, not sent explicitly. This
        # is why the prompt uses JSON API for merge rather than these CLI flags.
        self.assertEqual(writes[0][2], {"sha": "a" * 40})
        body = {"sha": "a" * 40, "squash": False,
                "should_remove_source_branch": False, "auto_merge": False}
        path = Path(self.tmp.name) / "merge choice.json"
        path.write_text(json.dumps(body))
        result = subprocess.run(["glab", "api", "--hostname", self.host, "--method", "PUT",
                                 "projects/73/merge_requests/42/merge", "--input", str(path)],
                                env=self.env, cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls[-1][2], body)
        for status in (403, 409, 405, 422):
            self.failure = ("unused", 1, status)
            result = subprocess.run(["glab", "api", "--hostname", self.host, "--method", "PUT",
                                     "projects/73/merge_requests/42/merge", "--input", str(path)],
                                    env=self.env, cwd=self.tmp.name, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(status), result.stderr)


if __name__ == "__main__":
    unittest.main()
