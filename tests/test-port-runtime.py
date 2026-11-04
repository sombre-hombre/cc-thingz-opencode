"""Integration: retained worktree/resume state plus overrides, not prompt prose."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/planning/skills/exec/scripts'
spec = importlib.util.spec_from_file_location('wt', SCRIPTS / 'worktree.py')
wt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wt)


class Restart(unittest.TestCase):
    def test_retained_move_and_durable_attempt_with_overrides(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='port-restart.') as tmp:
            base = Path(tmp)
            source = base / 'source with spaces'
            source.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.PIPE)
            git('init', '-qb', 'main')
            git('config', 'user.name', 'Port runtime')
            git('config', 'user.email', 'test@example.invalid')
            plan = source / 'plan.md'
            plan.write_text('### Task 1: Produce\n- [ ] produce\n')
            project = source / '.opencode/exec-plan/prompts/task.md'
            project.parent.mkdir(parents=True)
            project.write_text('project {{WORKING_DIRECTORY}}\n')
            git('add', '.')
            git('commit', '-qm', 'committed inputs')
            # Dirty source override must NOT leak into the isolated checkout.
            project.write_text('dirty source only\n')
            before = wt.snapshot(source)
            record = wt.create(source, plan, base / 'retained run')
            work, manifest = Path(record['directory']), Path(record['manifest'])
            with self.assertRaisesRegex(ValueError, 'session directory'):
                wt.verify(manifest, source)  # A failed move retains the owned tree.
            wt.verify(manifest, work)  # Resume the SAME manifest after actual move.
            with self.assertRaises((ValueError, OSError)):
                wt.create(source, plan, base / 'retained run')
            user = base / 'user data with spaces'
            (user / 'agents').mkdir(parents=True)
            (user / 'agents/quality.txt').write_text('user quality\n')
            def resolve(name):
                return subprocess.run(['bash', str(SCRIPTS / 'resolve-file.sh'), name, str(user)],
                                      cwd=work, capture_output=True, text=True)
            self.assertEqual(resolve('prompts/task.md').stdout, 'project {{WORKING_DIRECTORY}}\n')
            self.assertEqual(resolve('agents/quality.txt').stdout, 'user quality\n')
            self.assertEqual(resolve('agents/smells.txt').stdout,
                             (SCRIPTS.parent / 'references/agents/smells.txt').read_text())
            self.assertNotEqual(resolve('../escape').returncode, 0)
            self.assertNotEqual(resolve('prompts/missing.md').returncode, 0)
            progress, moved_plan = base / 'progress.txt', Path(record['plan'])
            def init():
                return subprocess.run(['bash', str(SCRIPTS / 'init-progress.sh'), str(progress), str(moved_plan),
                                       record['branch']], cwd=work, check=True, capture_output=True)
            def next_task():
                proc = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), 'next', str(moved_plan),
                                       str(progress), '0'], cwd=work, capture_output=True, text=True)
                return json.loads(proc.stdout)
            init()
            self.assertEqual(next_task()['state'], 'dispatch')
            saved = progress.read_bytes()
            init()  # Process restart must not reset attempts or truncate progress.
            self.assertEqual(progress.read_bytes(), saved)
            self.assertEqual(next_task()['state'], 'failed')
            self.assertIn('[ ]', moved_plan.read_text())
            self.assertEqual(wt.snapshot(source), before)


if __name__ == '__main__':
    unittest.main()
