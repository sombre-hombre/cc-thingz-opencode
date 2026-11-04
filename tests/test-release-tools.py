#!/usr/bin/env python3
"""Release behavior through actual Git/glab; all HTTP writes are loopback only."""
import copy
import hashlib
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
SCRIPTS = ROOT / "plugins/release-tools/skills/release/scripts"
HELPER = SCRIPTS / "release.py"
spec = importlib.util.spec_from_file_location("release", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("glab"):
            self.fail("installed glab required; not a skipped success")
        self.tmp = tempfile.TemporaryDirectory(prefix="release fixture ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo with spaces"
        self.repo.mkdir()
        self.host = "gitlab.fixture.test"
        self.calls = []
        self.pages = [[self.mr(7, "feat: add auth")], [self.mr(101, "fix(exec): fix timeout")]]
        self.failure = None
        self.release = None
        self.existing = False
        self.remote_tag = None
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, data, headers=None):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path.removeprefix("/api/v4/")
                query = parse_qs(parsed.query)
                page = int(query.get("page", ["1"])[0])
                test.calls.append(("GET", path, query))
                if test.failure and test.failure[:2] == (path, page):
                    self.reply(test.failure[2], {"message": "fixture denied"})
                elif path in {"projects/team%2Fplatform%2Fservice", "projects/73"}:
                    self.reply(200, {"id": 73, "path_with_namespace": "team/platform/service"})
                elif path == "projects/73/merge_requests":
                    headers = {}
                    if page < len(test.pages):
                        headers["Link"] = f'<http://{test.api_host}/api/v4/{path}?state=merged&scope=all&per_page=100&page={page+1}>; rel="next"'
                    self.reply(200, test.pages[page - 1], headers)
                elif "/repository/tags/" in path:
                    self.reply(200, test.remote_tag) if test.remote_tag else self.reply(404, {"message": "tag absent"})
                elif "/releases/" in path:
                    value = test.release or ({"tag_name": "v0.1.0"} if test.existing else None)
                    self.reply(200, value) if value else self.reply(404, {"message": "release absent"})
                else:
                    self.reply(404, {"message": "unexpected route"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                test.calls.append(("POST", self.path, body))
                if test.failure:
                    self.reply(test.failure[2], {"message": "publication denied"})
                    return
                test.release = {**body, "commit": {"id": body.get("ref")},
                                "_links": {"self": f"https://{test.host}/team/platform/service/-/releases/{body['tag_name']}"}}
                self.reply(201, test.release)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api_host = f"127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root),
                    "XDG_CONFIG_HOME": str(self.root), "GLAB_CONFIG_DIR": str(self.root),
                    "GITLAB_HOST": self.host, "GITLAB_API_HOST": self.api_host,
                    "GITLAB_TOKEN": "fixture-only", "GLAB_API_PROTOCOL": "http",
                    "GLAB_CHECK_UPDATE": "false", "GLAB_SEND_TELEMETRY": "false",
                    "NO_COLOR": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test Author")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        self.git("remote", "add", "origin", f"git@{self.host}:team/platform/service.git")
        self.git("commit", "--allow-empty", "-qm", "initial")

    @staticmethod
    def mr(iid, title, date="2026-08-20T03:00:00Z"):
        return {"id": 9000 + iid, "iid": iid, "project_id": 73, "state": "merged",
                "title": title, "merged_at": date, "author": {"username": f"user{iid}"}}

    def command(self, args, **kwargs):
        return subprocess.run(args, cwd=self.repo, env=self.env, capture_output=True,
                              text=True, timeout=30, **kwargs)

    def git(self, *args):
        result = self.command(["git", *args])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def helper(self, *args):
        return self.command(["python3", str(HELPER), *args])

    def ok(self, *args):
        result = self.helper(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, subject, author=None):
        args = ["commit", "--allow-empty", "-qm", subject]
        if author:
            args += ["--author", author]
        self.git(*args)

    def test_upstream_version_defaults_bumps_prerelease_and_errors(self):
        for kind, expected in [("major", "v1.0.0"), ("minor", "v0.1.0"), ("hotfix", "v0.0.1")]:
            self.assertEqual(self.ok("version", kind), expected)
        self.git("tag", "v1.2.3")
        for kind, expected in [("major", "v2.0.0"), ("minor", "v1.3.0"), ("hotfix", "v1.2.4")]:
            self.assertEqual(self.ok("version", kind), expected)
        self.commit("next")
        self.git("tag", "v2.5.9-rc1")
        self.assertEqual(self.ok("version", "hotfix"), "v2.5.10")
        self.assertEqual(self.ok("version", "minor"), "v2.6.0")
        for bad in ("vfoo.bar.baz", "v1.2.3.4", "v08.2.3", "v1.2.3-01"):
            self.commit("next bad")
            self.git("tag", bad)
            result = self.helper("version", "minor")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("cannot parse version", result.stderr)
        for kind in ("", "patch", "$(touch nope)"):
            self.assertNotEqual(self.helper("version", kind).returncode, 0)
        self.assertFalse((self.repo / "nope").exists())

    def test_gitlab_nested_ssh_https_and_unknown_missing_remote_fail(self):
        for url in [f"git@{self.host}:team/platform/service.git",
                    f"https://{self.host}/team/platform/service.git",
                    f"ssh://git@{self.host}:2222/team/platform/service.git"]:
            self.git("remote", "set-url", "origin", url)
            self.assertEqual(self.ok("detect"), "gitlab")
            self.assertEqual(self.calls[-1][1], "projects/team%2Fplatform%2Fservice")
        self.failure = ("projects/team%2Fplatform%2Fservice", 1, 401)
        self.assertNotEqual(self.helper("detect").returncode, 0)
        self.git("remote", "remove", "origin")
        self.assertNotEqual(self.helper("detect").returncode, 0)
        self.git("remote", "add", "origin", "/local/path")
        self.assertNotEqual(self.helper("detect").returncode, 0)

    def test_actual_pagination_notes_categories_dedup_and_commit_fallback(self):
        self.commit("feat: add auth")  # Duplicate MR wins.
        self.commit("chore: tidy scripts")
        self.commit("unprefixed subject")
        result = self.ok("notes")
        self.assertIn("- add auth !7 @user7", result)
        self.assertEqual(result.count("- add auth "), 1)
        self.assertIn("- fix timeout !101 @user101", result)
        self.assertRegex(result, r"- tidy scripts [0-9a-f]{7}")
        self.assertIn("**Other**", result)
        queries = [c[2] for c in self.calls if c[1] == "projects/73/merge_requests"]
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0]["state"], ["merged"])
        self.assertEqual(queries[0]["scope"], ["all"])
        self.assertEqual(queries[0]["per_page"], ["100"])
        self.pages = [[]]
        self.assertIn("add auth", self.ok("notes"))

    def test_tag_creator_cutoff_timezone_and_exact_commit_range(self):
        self.env.update(GIT_AUTHOR_DATE="2026-08-19T20:00:00Z", GIT_COMMITTER_DATE="2026-08-19T20:00:00Z")
        self.commit("feat: already shipped")
        self.env["GIT_COMMITTER_DATE"] = "2026-08-20T04:00:00+02:00"
        self.git("tag", "-a", "v1.0.0", "-m", "release")
        self.env.pop("GIT_AUTHOR_DATE")
        self.env.pop("GIT_COMMITTER_DATE")
        self.commit("fix: after tag")
        self.pages = [[self.mr(1, "fix: before cutoff", "2026-08-20T01:30:00Z"),
                       self.mr(2, "fix: exact cutoff", "2026-08-20T02:00:00Z")],
                      [self.mr(3, "feat: after cutoff", "2026-08-20T02:30:00Z")]]
        notes = self.ok("notes")
        self.assertIn("after cutoff !3", notes)
        self.assertIn("after tag", notes)
        for excluded in ("before cutoff", "exact cutoff", "already shipped"):
            self.assertNotIn(excluded, notes)

    def test_untagged_twenty_commits_and_merge_exclusion(self):
        self.pages = [[]]
        for n in range(23):
            self.commit(f"fix: item {n:02d}")
        result = self.ok("notes")
        self.assertNotIn("item 02", result)
        self.assertIn("item 03", result)
        self.assertEqual(result.count("- item "), 20)
        self.git("checkout", "-qb", "side", "HEAD~2")
        self.commit("feat: side")
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "side", "-m", "merge-only-marker")
        self.assertNotIn("merge-only-marker", self.ok("notes"))

    def test_later_api_auth_rights_rate_limit_and_semantic_errors_no_stdout(self):
        for status in (401, 403, 404, 429, 500):
            self.failure = ("projects/73/merge_requests", 2, status)
            result = self.helper("notes")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(status), result.stderr)
        self.failure = None
        for field in ("merged_at", "iid", "title", "author", "state", "project_id"):
            original = copy.deepcopy(self.pages)
            self.pages[1][0].pop(field)
            result = self.helper("notes")
            self.assertNotEqual(result.returncode, 0, field)
            self.assertEqual(result.stdout, "")
            self.pages = original
        self.pages[1][0]["merged_at"] = "not-a-date"
        self.assertNotEqual(self.helper("notes").returncode, 0)

    def test_last_tag_single_multiple_authors_pipes_and_drilldown(self):
        self.assertEqual(self.ok("last-tag"), "No tags found in repository")
        self.git("tag", "not-semver")
        self.assertIn("No commits since this tag", self.ok("last-tag"))
        self.commit("fix: pipe | in subject")
        oid = self.git("rev-parse", "--short", "HEAD")
        one = self.ok("last-tag")
        self.assertIn("Author: Test Author", one)
        self.assertIn(r"pipe \| in subject", one)
        self.assertNotIn("| Date | Author |", one)
        self.assertIn("test@example.invalid", self.ok("details", oid))
        self.commit("feat: second", "Other Author <other@example.invalid>")
        self.assertIn("| Date | Author |", self.ok("last-tag"))
        self.assertEqual(self.ok("details", "all").count("Commit:"), 2)
        for selected in ("--bad-option", "not-semver", self.git("rev-parse", "HEAD~2")):
            self.assertNotEqual(self.helper("details", selected).returncode, 0)

    def make_preview(self):
        data = json.loads(self.ok("preview", "minor"))
        path = self.root / "preview with spaces.json"
        path.write_text(json.dumps(data))
        confirm = data["version"] + "@" + hashlib.sha256(path.read_bytes()).hexdigest()
        return data, path, confirm

    def test_deterministic_preview_only_no_tags_commits_changelog_mutation_or_writes(self):
        (self.repo / "changelog.md").write_text("# Changes\n\n## Unreleased\n")
        self.git("add", "changelog.md")
        self.git("commit", "-qm", "docs: changelog")
        before = self.git("rev-parse", "HEAD")
        data, path, confirm = self.make_preview()
        self.assertEqual(data["version"], "v0.1.0")
        self.assertEqual(data["changelog"], "changelog.md")
        self.assertEqual(data["state"], "preview-only")
        self.assertEqual(self.git("tag", "--list"), "")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "changelog.md").read_text(), "# Changes\n\n## Unreleased\n")
        self.assertTrue(all(c[0] == "GET" for c in self.calls))
        result = self.helper("publish", str(path), "--confirm", "yes")
        self.assertNotEqual(result.returncode, 0)
        path.write_text(path.read_text() + "\n")
        self.assertNotEqual(self.helper("publish", str(path), "--confirm", confirm).returncode, 0)
        (self.repo / "dirty").write_text("untracked")
        self.assertNotEqual(self.helper("preview", "minor").returncode, 0)

    def test_publication_guard_actual_glab_arguments_and_readback_loopback_only(self):
        data, path, confirm = self.make_preview()
        self.assertNotEqual(self.helper("publish", str(path), "--confirm", confirm).returncode, 0)
        self.git("tag", "-a", data["version"], data["head"], "-m", data["title"])
        self.remote_tag = {"name": data["version"], "message": data["title"], "commit": {"id": data["head"]}}
        result = self.helper("publish", str(path), "--confirm", confirm)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["tag_name"], data["version"])
        writes = [c for c in self.calls if c[0] == "POST"]
        self.assertEqual(len(writes), 1)
        body = writes[0][2]
        self.assertEqual(body["name"], "Version 0.1.0")
        self.assertEqual(body["description"], data["notes"])
        self.assertEqual(body["tag_name"], "v0.1.0")
        self.assertEqual(body["ref"], data["head"])
        # Existing release must NOT be updated (glab defaults to updating).
        before = len(writes)
        self.assertNotEqual(self.helper("publish", str(path), "--confirm", confirm).returncode, 0)
        self.assertEqual(len([c for c in self.calls if c[0] == "POST"]), before)

    def test_publish_wrong_remote_sha_dirty_and_cli_failure(self):
        data, path, confirm = self.make_preview()
        self.git("tag", "-a", data["version"], "-m", data["title"])
        self.remote_tag = {"name": data["version"], "message": data["title"], "commit": {"id": "a" * 40}}
        self.assertNotEqual(self.helper("publish", str(path), "--confirm", confirm).returncode, 0)
        self.assertFalse(any(c[0] == "POST" for c in self.calls))
        self.remote_tag["commit"]["id"] = data["head"]
        self.failure = ("unused", 1, 403)
        result = self.helper("publish", str(path), "--confirm", confirm)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("403", result.stderr)
        self.failure = None
        self.commit("HEAD changed")
        self.assertNotEqual(self.helper("publish", str(path), "--confirm", confirm).returncode, 0)

    def test_lightweight_tags_cutoff_and_publication_rejection(self):
        self.env["GIT_COMMITTER_DATE"] = "2026-08-20T04:00:00+02:00"
        self.commit("fix: shipped")
        self.env.pop("GIT_COMMITTER_DATE")
        self.git("tag", "v1.2.3")
        self.pages = [[self.mr(1, "fix: before", "2026-08-20T01:30:00Z"),
                       self.mr(2, "fix: after", "2026-08-20T02:30:00Z")]]
        self.assertNotIn("- before", self.ok("notes"))
        self.assertIn("- after !2", self.ok("notes"))
        data, path, confirm = self.make_preview()
        self.git("tag", data["version"])
        result = self.helper("publish", str(path), "--confirm", confirm)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("annotated", result.stderr)
        self.assertTrue(all(c[0] == "GET" for c in self.calls))

    def test_malformed_pages_timeout_and_readback_mismatch_are_failures(self):
        self.pages = [[self.mr(1, "feat: fine")], {"message": "not an array"}]
        result = self.helper("notes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.pages = [[self.mr(1, "feat: fine")]]
        data, path, confirm = self.make_preview()
        self.git("tag", "-a", data["version"], "-m", data["title"])
        old_cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            with patch.object(module, "transport", side_effect=subprocess.TimeoutExpired("glab", 120)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    module.publish(path, confirm)
            remote_tag = {"name": data["version"], "message": data["title"], "commit": {"id": data["head"]}}
            class Transport:
                def api(self, host, endpoint):
                    if "/repository/tags/" in endpoint:
                        return remote_tag
                    if "/releases/" in endpoint:
                        return {"tag_name": data["version"], "description": "wrong notes"}
                    return {"id": 73, "path_with_namespace": "team/platform/service"}
            # Unit-only negative readback; no model, no actual publication.
            original_run = module.run
            def fake_create(args):
                return "fixture CLI success" if args[:3] == ["glab", "release", "create"] else original_run(args)
            with patch.object(module, "transport", return_value=Transport()), patch.object(module, "run", side_effect=fake_create):
                with self.assertRaisesRegex(module.ReleaseError, "readback mismatch"):
                    module.publish(path, confirm)
        finally:
            os.chdir(old_cwd)

    def test_shell_entrypoints_symlink_and_manifest(self):
        link = self.root / "linked scripts"
        link.symlink_to(SCRIPTS, target_is_directory=True)
        for name, args in [("detect-platform.sh", []), ("get-notes.sh", ["gitlab"]),
                           ("calc-version.sh", ["minor"])]:
            result = self.command(["bash", str(link / name), *args])
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.command(["bash", str(link / "get-notes.sh"), "github"]).returncode, 0)
        manifest = json.loads((ROOT / "install-manifest.json").read_text())
        entry = next(s for s in manifest["skills"] if s["id"] == "release")
        self.assertEqual(entry["source"], "plugins/release-tools/skills/release")
        self.assertTrue((ROOT / entry["source"] / "SKILL.md").is_file())
        command = (ROOT / "commands/release.md").read_text()
        self.assertIn('id:"release"', command.replace(" ", ""))
        self.assertIn("$ARGUMENTS", command)

    def test_relocated_copied_skills_use_installed_pr_transport(self):
        config = self.root / "opencode/skills"
        copy_dir = config / "release"
        shutil.copytree(SCRIPTS.parent, copy_dir)
        pr_dir = config / "pr/scripts"
        pr_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "plugins/review/skills/pr/scripts/gitlab-context.py", pr_dir)
        result = self.command(["python3", str(copy_dir / "scripts/release.py"), "notes"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("!101 @user101", result.stdout)
        (pr_dir / "gitlab-context.py").unlink()
        result = self.command(["python3", str(copy_dir / "scripts/release.py"), "notes"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_cli_and_bad_repository_not_empty_success(self):
        binaries = self.root / "git-only-bin"
        binaries.mkdir()
        (binaries / "git").symlink_to(shutil.which("git"))
        env = {**self.env, "PATH": str(binaries)}
        result = subprocess.run([shutil.which("python3"), str(HELPER), "notes"],
                                cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("glab", result.stderr)
        result = subprocess.run(["python3", str(HELPER), "version", "minor"],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
