#!/usr/bin/env python3
"""Behavior/error tests for V2 review boundaries, not prompt wording mirrors."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import signal
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from process_helpers import wait_stopped

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/planning/skills/exec/scripts"
spec = importlib.util.spec_from_file_location("review", SCRIPTS / "exec-review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="exec review ")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def launch(self, body, command=None, timeout=5):
        reviewer = self.work / "reviewer"
        reviewer.write_text("#!/bin/bash\n" + body)
        reviewer.chmod(0o755)
        prompt = self.work / "prompt with spaces"
        prompt.write_text('`false` $(touch MUST_NOT_EXIST) "quotes"\nCRITICAL prompt definition')
        outdir = self.work / ("output " + str(len(list(self.work.glob("output *")))))
        with patch.dict(os.environ, {"PATH": str(self.work) + os.pathsep + os.environ["PATH"]}):
            return review.external({"cwd": str(self.work), "prompt_file": str(prompt),
                                    "command": command or "reviewer", "output_dir": str(outdir), "timeout": timeout})

    def test_classification_matrix(self):
        cases = [(0, "NO ISSUES FOUND", "CRITICAL echo", "clean", False),
                 (0, "NO ISSUES FOUND\nMAJOR: a:1 bug", "", "findings", True),
                 (0, "MINOR: a:1 nit\nwrapped description", "", "findings", False),
                 (0, "major: a:1 bug", "", "findings", True),
                 (0, "majority", "", "failed", False),
                 (0, "FAILED: reviewer could not inspect files; NO ISSUES FOUND cannot be established", "", "failed", False),
                 (0, "FAILED: unreadable files\nNO ISSUES FOUND", "", "failed", False),
                 (0, "NO ISSUES FOUND cannot be established", "", "failed", False),
                 (0, "NO ISSUES FOUND\nMINOR: nit", "", "findings", False),
                 (0, "", "NO ISSUES FOUND", "failed", False),
                 (0, " \n", "", "failed", False),
                 (3, "NO ISSUES FOUND", "crashed", "failed", False),
                 (127, "", "inner tool absent", "failed", False),
                 (127, "", "error: run-external-review: tool absent", "skipped", False)]
        for rc, out, err, state, blocking in cases:
            with self.subTest(out=out, err=err):
                result = review.classify(rc, out, err)
                self.assertEqual((result["state"], result["has_blocking"]), (state, blocking))
        self.assertEqual(review.classify(0, "NO ISSUES FOUND", "", True)["state"], "failed")

    def test_real_argv_separate_streams_and_marker(self):
        result = self.launch('printf "%s" "${!#}"\nprintf "MAJOR stderr" >&2\n', "reviewer ; touch MUST_NOT_EXIST")
        self.assertIn("$(touch MUST_NOT_EXIST)", Path(result["stdout_file"]).read_text())
        self.assertEqual(Path(result["stderr_file"]).read_text(), "MAJOR stderr")
        self.assertFalse((self.work / "MUST_NOT_EXIST").exists())
        failed = self.launch('echo inner missing >&2\nexit 127\n')
        self.assertEqual((failed["state"], failed["returncode"]), ("failed", 127))
        skipped = self.launch("", "definitely-absent-reviewer-task9")
        self.assertEqual((skipped["state"], skipped["returncode"]), ("skipped", 127))
        self.assertIn("run-external-review:", skipped["reason"])

    def test_timeout_empty_failure_and_status_file(self):
        result = self.launch("sleep 30\n", timeout=.05)
        self.assertEqual((result["state"], result["reason"], result["timed_out"]), ("failed", "timeout", True))
        self.assertEqual(json.loads(Path(result["stdout_file"]).with_name("status.json").read_text()), result)
        self.assertEqual(self.launch('echo "NO ISSUES FOUND" >&2\n')["state"], "failed")
        self.assertEqual(self.launch('echo failed >&2\nexit 4\n')["returncode"], 4)
        self.assertEqual(self.launch('echo NO ISSUES FOUND\n')["state"], "clean")

    def test_no_overwrite_bad_requests(self):
        prompt = self.work / "p"
        prompt.write_text("review")
        request = {"cwd": str(self.work), "prompt_file": str(prompt), "command": "false", "output_dir": str(self.work / "out")}
        for bad in (0, -1, True, float("inf")):
            with self.assertRaises(ValueError):
                review.external({**request, "timeout": bad})
        review.external(request)
        with self.assertRaises(FileExistsError):
            review.external(request)
        with self.assertRaises(ValueError):
            review.external({**request, "cwd": "."})

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.work, text=True, stderr=subprocess.PIPE).strip()

    def test_signal_and_timeout_kill_wrapper_descendants(self):
        for sig in (None, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig):
                run = self.work / str(sig)
                run.mkdir()
                child = run / 'child.py'
                child.write_text('import os,signal,time\nfrom pathlib import Path\n'
                                 'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                                 f'Path({str(run / "pid")!r}).write_text(str(os.getpid()))\n'
                                 'time.sleep(60)\n')
                wrapper = run / 'wrapper'
                wrapper.write_text('#!/bin/bash\npython3 ' + repr(str(child)) + ' &\nwait\n')
                wrapper.chmod(0o755)
                prompt = run / 'prompt'
                prompt.write_text('review')
                request = run / 'request.json'
                request.write_text(json.dumps({'cwd': str(run), 'command': 'wrapper',
                    'prompt_file': str(prompt), 'output_dir': str(run / 'out'), 'timeout': .8 if sig is None else 30}))
                proc = subprocess.Popen(['python3', str(SCRIPTS / 'exec-review.py'), 'external', str(request)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        env={**os.environ, 'PATH': str(run) + os.pathsep + os.environ['PATH']})
                try:
                    deadline = time.monotonic() + 5
                    while not (run / 'pid').exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue((run / 'pid').exists())
                    pid = int((run / 'pid').read_text())
                    if sig is not None:
                        proc.send_signal(sig)
                    out, err = proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode, 0, err)
                    self.assertEqual(json.loads(out)['state'], 'failed' if sig is None else 'cancelled')
                    self.assertTrue(wait_stopped(pid), 'reviewer survived')
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    proc.communicate(timeout=10)

    def repo(self):
        self.git("init", "-qb", "main")
        self.git("config", "user.name", "Review test")
        self.git("config", "user.email", "review@example.invalid")
        (self.work / "code").write_text("before\n")
        self.git("add", "code")
        self.git("commit", "-qm", "base")
        self.git("switch", "-qc", "feature")

    def test_finalize_preserves_foreign_staged_and_unowned_history(self):
        self.repo()
        (self.work / "code").write_text("after\n")
        self.git("commit", "-qam", "run")
        oid = self.git("rev-parse", "HEAD")
        req = {"cwd": str(self.work), "default_branch": "main", "owned_commits": [oid], "authorized": True}
        self.assertEqual(review.finalize_check(req)["state"], "ready")
        self.assertIn("unrelated", review.finalize_check({**req, "owned_commits": []})["reason"])
        self.assertIn("authorization", review.finalize_check({**req, "authorized": False})["reason"])
        (self.work / "foreign").write_text("keep staged\n")
        self.git("add", "foreign")
        before = self.git("diff", "--cached", "--binary")
        self.assertIn("dirty", review.finalize_check(req)["reason"])
        self.assertEqual(self.git("diff", "--cached", "--binary"), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), oid)

    def test_finalize_active_operation_and_bad_ref_are_not_ready(self):
        self.repo()
        req = {"cwd": str(self.work), "default_branch": "main", "owned_commits": [], "authorized": True}
        marker = self.work / ".git/MERGE_HEAD"
        marker.write_text(self.git("rev-parse", "HEAD") + "\n")
        before = marker.read_bytes()
        self.assertIn("active VCS operation", review.finalize_check(req)["reason"])
        self.assertEqual(marker.read_bytes(), before)
        marker.unlink()
        with self.assertRaises(subprocess.CalledProcessError):
            review.finalize_check({**req, "default_branch": "missing-ref"})

    def test_cli_failure_is_nonzero_not_clean_json(self):
        bad = self.work / "request.json"
        bad.write_text("not json")
        for args in (["external", str(bad)], ["stats", "latest"], ["unknown", "x"]):
            proc = subprocess.run(["python3", str(SCRIPTS / "exec-review.py"), *args], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            self.assertIn("exec-review:", proc.stderr)

    def test_codex_inherits_model_and_no_overrides_exactly_one(self):
        self.repo()
        binary = self.work / "codex"
        binary.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        binary.chmod(0o755)
        env = {**os.environ, "PATH": str(self.work) + os.pathsep + os.environ["PATH"]}
        env.pop("CODEX_MODEL", None)
        env.pop("CODEX_NO_OVERRIDES", None)
        def run(extra):
            return json.loads(subprocess.check_output(["bash", str(SCRIPTS / "run-external-review.sh"), "", "review"],
                                                     cwd=self.work, env={**env, **extra}, text=True))
        inherited = run({})
        self.assertFalse(any(a.startswith("model=") for a in inherited))
        self.assertIn("model_reasoning_effort=xhigh", inherited)
        for value in ("0", "false", ""):
            self.assertIn("model=custom", run({"CODEX_MODEL": "custom", "CODEX_NO_OVERRIDES": value}))
        self.assertEqual(run({"CODEX_MODEL": "custom", "CODEX_NO_OVERRIDES": "1"}),
                         ["exec", "--sandbox", "read-only", "review"])
        linked = self.work / "linked-review.sh"
        linked.symlink_to(SCRIPTS / "run-external-review.sh")
        linked_result = json.loads(subprocess.check_output(["bash", str(linked), "", "linked prompt"],
                                  cwd=self.work, env={**env, "CODEX_NO_OVERRIDES": "1"}, text=True))
        self.assertEqual(linked_result, ["exec", "--sandbox", "read-only", "linked prompt"])

    def test_stats_root_children_pagination_failure(self):
        ids = ["ses_root", "ses_child1", "ses_child2"]
        requests = []
        def api(path):
            requests.append(path)
            if path.endswith("/context"):
                return {"data": [{"content": [{"type": "tool", "name": "subagent", "time": {"ran": 1, "completed": 2}, "state": {"status": "completed", "metadata": {"sessionID": "ses_child1"}, "input": {"description": "Phase7 quality"}}}]}]}
            if path.startswith("/api/session?"):
                q = parse_qs(urlsplit(path).query)
                if q["parentID"] == [ids[0]]:
                    child = ids[2] if "cursor" in q else ids[1]
                    return {"data": [{"id": child, "parentID": ids[0]}], "cursor": {} if "cursor" in q else {"next": "page two"}}
                return {"data": []}
            sid = path.rsplit("/", 1)[-1]
            return {"data": {"id": sid, "parentID": ids[0] if sid != ids[0] else None,
                             "tokens": {"input": 12}, "cost": .1, "time": {"created": 1, "updated": 3}}}
        result = review.stats(ids[0], api)
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual([s["id"] for s in result["sessions"]], ids)
        self.assertTrue(any("cursor=page+two" in p for p in requests))
        self.assertEqual(len(result["sessions"][0]["tools"]), 1)
        self.assertEqual(result["sessions"][0]["tools"][0]["child_session_id"], "ses_child1")
        def failed(path):
            raise ValueError("API denied")
        unavailable = review.stats(ids[0], failed)
        self.assertEqual(unavailable["coverage"], "unavailable")
        self.assertIn("API denied", unavailable["errors"][0])
        with self.assertRaises(ValueError):
            review.stats("latest", api)

    def test_smoke_wait_reconnect_never_redispatches(self):
        smoke_spec = importlib.util.spec_from_file_location("smoke", ROOT / "tests/smoke/exec-review-phases.py")
        smoke = importlib.util.module_from_spec(smoke_spec)
        smoke_spec.loader.exec_module(smoke)
        calls, saved = [], []
        def api(method, path, body):
            calls.append((method, path, body))
            if len(calls) == 1:
                raise RuntimeError("native CLI TimeoutError")
        smoke.wait_idle(api, lambda name, data: saved.append(data), "ses_same")
        self.assertEqual(calls, [("POST", "/api/experimental/session/ses_same/wait", {})] * 2)
        self.assertEqual(saved[0]["sessionID"], "ses_same")
        def denied(*args):
            raise RuntimeError("permission denied")
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            smoke.wait_idle(denied, lambda *a: None, "ses_same")

    def test_native_api_large_json_uses_regular_stdout_file(self):
        binary = self.work / "opencode"
        binary.write_text('#!/usr/bin/env python3\nimport json,os,stat\n'
                          'text=json.dumps({"data":{"large":"x"*300000}})\n'
                          'regular=stat.S_ISREG(os.fstat(1).st_mode)\n'
                          'os.write(1,(text if regular else text[:262144]).encode())\n')
        binary.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(self.work) + os.pathsep + os.environ["PATH"]}):
            data = review.native_api("/api/session/ses_fixture/context")
        self.assertEqual(len(data["data"]["large"]), 300000)

    def test_smoke_findings_require_nonempty_actual_response(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tests/smoke'))
        from smoke_helpers import assert_findings_delivered
        for content in ([], [{'type': 'text', 'text': '<subagent>\n\n</subagent>'}]):
            with self.assertRaisesRegex(AssertionError, 'no actual final response'):
                assert_findings_delivered({'state': {'status': 'completed', 'content': content}}, 'anything', '')
        call = {'state': {'content': [{'type': 'text', 'text': '<subagent>\nMAJOR: full\ncontinued\n</subagent>'}]}}
        with self.assertRaisesRegex(AssertionError, 'full unfiltered'):
            assert_findings_delivered(call, 'MAJOR: full', '')
        assert_findings_delivered(call, '', 'read evidence MAJOR: full\ncontinued')

    def test_shared_smoke_transport_result_errors_and_timeout(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tests/smoke'))
        import smoke_helpers as smoke
        def response(argv, stdout, **kwargs):
            self.assertEqual(argv, ['opencode', 'api', 'post', '/fixture', '--data', '{"value": 7}'])
            self.assertEqual(kwargs['timeout'], 1800)
            stdout.write(json.dumps({'data': 'x' * 300000}))
            return subprocess.CompletedProcess(argv, 0, stderr='')
        with patch.object(smoke.subprocess, 'run', response):
            self.assertEqual(len(smoke.api('POST', '/fixture', {'value': 7})['data']), 300000)
        with patch.object(smoke.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, stderr='denied')):
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                smoke.api('GET', '/fixture')
        with patch.object(smoke.subprocess, 'run', side_effect=subprocess.TimeoutExpired('opencode', 1)):
            with self.assertRaisesRegex(RuntimeError, 'TimeoutError'):
                smoke.api('GET', '/fixture', timeout=1)

    def test_shared_smoke_transport_custom_executable_large_json(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tests/smoke'))
        from smoke_helpers import api
        binary = self.work / 'custom cli'
        binary.write_text('#!/usr/bin/env python3\nimport json,os,stat,sys\n'
                          'assert sys.argv[1:] == ["api", "get", "/fixture/context"]\n'
                          'text=json.dumps({"data":"x"*300000})\n'
                          'regular=stat.S_ISREG(os.fstat(1).st_mode)\n'
                          'os.write(1,(text if regular else text[:262144]).encode())\n')
        binary.chmod(0o755)
        self.assertEqual(len(api('GET', '/fixture/context', timeout=1200,
                                 executable=str(binary))['data']), 300000)

    def test_active_smokes_forward_binary_and_original_timeout(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tests/smoke'))
        for filename, endpoint in [('worktree-session.py', '/api/session/ses_parent'),
                                   ('exec-task-loop-active.py', '/api/info')]:
            with self.subTest(filename=filename):
                spec = importlib.util.spec_from_file_location('active_smoke', ROOT / 'tests/smoke' / filename)
                smoke = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(smoke)
                with patch.object(sys, 'argv', [filename, '--parent', 'ses_parent',
                                               '--authorize-current-model', '--binary', '/custom cli']), \
                     patch.object(smoke.tempfile, 'mkdtemp', return_value=str(self.work)), \
                     patch.object(smoke.subprocess, 'run') as service, \
                     patch.object(smoke, 'native_api', side_effect=RuntimeError('transport probe')) as transport:
                    with self.assertRaisesRegex(RuntimeError, 'transport probe'):
                        smoke.main()
                transport.assert_called_once_with('GET', endpoint, None, timeout=1200,
                                                  executable='/custom cli')
                self.assertEqual(service.call_args.args[0], ['/custom cli', 'service', 'status'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
