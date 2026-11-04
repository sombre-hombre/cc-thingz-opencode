#!/usr/bin/env python3
"""Behavioral admission, retry, rendering and progress tests (no model fixtures)."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/planning/skills/exec/scripts"
spec = importlib.util.spec_from_file_location("task_loop", SCRIPTS / "task-loop.py")
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)


class TaskLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="exec loop ")
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        oldcwd = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, oldcwd)
        self.plan = self.work / "plan with spaces.md"
        self.text = "# Plan\n### Task 1: Produce\n- [ ] produce\n### Iteration 2: Consume\n- [ ] consume\n"
        self.plan.write_text(self.text)
        self.progress = self.work / "progress.txt"
        self.init()

    def init(self, plan=None, check=True):
        return subprocess.run(["bash", str(SCRIPTS / "init-progress.sh"), str(self.progress),
                               str(plan or self.plan), "feature"], capture_output=True, text=True, check=check)

    def playbook_move_gate(self, playbook):
        # Execute the admission command from the active instructions, not a
        # duplicate helper-only model of their post-child/completion policy.
        text = (SCRIPTS.parent / 'references/prompts' / playbook).read_text()
        commands = [block.strip() for block in re.findall(r'```bash\n(.*?)\n```', text, re.S)
                    if 'task-loop.py check-move' in block]
        self.assertEqual(len(commands), 1, playbook)
        argv = [arg.replace('<EXEC_DIR>', str(SCRIPTS.parent))
                .replace('<absolute-plan>', str(self.plan))
                .replace('<absolute-progress>', str(self.progress))
                for arg in shlex.split(commands[0])]
        return subprocess.run(argv, cwd=self.work, capture_output=True, text=True)

    def test_selection_missing_ambiguous_and_completed(self):
        self.assertEqual(loop.select(self.work), str(self.plan))
        self.assertEqual(loop.select(self.work, self.plan.name), str(self.plan))
        (self.work / "completed").mkdir()
        (self.work / "completed/old.md").write_text(self.text)
        self.assertEqual(loop.select(self.work), str(self.plan))
        other = self.work / "other.md"
        other.write_text(self.text)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            loop.select(self.work)
        other.unlink()
        self.plan.unlink()
        with self.assertRaises(ValueError):
            loop.select(self.work)
        with self.assertRaises(OSError):
            loop.select(self.work, self.plan)

    def test_malformed_tasks_are_not_complete(self):
        for text in ("# empty", "### Task 1: X\n", "### Task 0: X\n- [ ] x",
                     "### Task 1: X\n- [?] x", self.text + "### Task 1: duplicate\n- [ ] x",
                     self.text + "```\nnever closed"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.plan.write_text(text)
                loop.tasks(self.plan)

    def test_order_fences_retries_and_plan_not_return_text(self):
        self.plan.write_text("```markdown\n### Task 99: example\n- [ ] fake\n```\n" + self.text)
        first = loop.next_task(self.plan, self.progress, 1)
        self.assertEqual((first["state"], first["task"], first["attempt"]), ("dispatch", "Task 1", 1))
        # A return claim cannot advance the plan: fresh read still selects Task 1.
        second = loop.next_task(self.plan, self.progress, 1)
        self.assertEqual((second["task"], second["attempt"]), ("Task 1", 2))
        self.assertEqual(loop.next_task(self.plan, self.progress, 1)["state"], "failed")
        self.plan.write_text(self.plan.read_text().replace("[ ] produce", "[x] produce"))
        self.assertEqual(loop.next_task(self.plan, self.progress, 1)["task"], "Iteration 2")
        self.plan.write_text(self.plan.read_text().replace("[ ] consume", "[x] consume"))
        self.assertEqual(loop.next_task(self.plan, self.progress, 1)["state"], "tasks-complete")
        self.assertTrue(self.plan.exists())  # no terminal move during the loop

    def test_line_start_inline_backticks_cannot_hide_task_two(self):
        original_progress = self.progress.read_bytes()
        for literal in ('```literal```', '````literal `` nested````', '```<!--```'):
            with self.subTest(literal=literal):
                self.plan.write_text('### Task 1: Done\n- [x] done\n' + literal + '\n'
                                     '### Task 2: Required\n- [ ] required work\n' + literal + '\n')
                self.progress.write_bytes(original_progress)
                before = self.plan.read_bytes()
                result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), 'next',
                                         str(self.plan), str(self.progress), '0'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                dispatched = json.loads(result.stdout)
                self.assertEqual((dispatched['state'], dispatched['task']), ('dispatch', 'Task 2'))
                progress = self.progress.read_bytes()
                result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), 'check-move',
                                         str(self.plan), str(self.progress)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('pending', result.stderr)
                self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), (before, progress))

    def test_fence_text_suffix_cannot_hide_required_task(self):
        original_progress = self.progress.read_bytes()
        for marker in ('```', '~~~', '````', '~~~~'):
            for suffix in ('not-a-close', ' text', '\ttext', '\u00a0'):
                with self.subTest(marker=marker, suffix=suffix):
                    # Original bypass: false close, then true close misread as
                    # opener, then an inline literal misread as its close.
                    self.plan.write_text('### Task 1: Complete\n- [x] Done\n' + marker + 'text\n'
                                         + marker + suffix + '\n' + marker + '\n\n'
                                         '### Task 2: Required\n- [ ] Real pending work\n\n'
                                         '```literal```\n')
                    self.progress.write_bytes(original_progress)
                    self.assertEqual([t['id'] for t in loop.tasks(self.plan)], ['Task 1', 'Task 2'])
                    result = loop.next_task(self.plan, self.progress, 0)
                    self.assertEqual((result['state'], result['task']), ('dispatch', 'Task 2'))
                    before = self.plan.read_bytes(), self.progress.read_bytes()
                    with self.assertRaisesRegex(ValueError, 'pending'):
                        loop.check_move(self.plan, self.progress)
                    self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_fence_closing_contract_and_unfinished_blocks(self):
        for opener, invalid in [('```', '~~~'), ('````', '```'), ('~~~~', '~~~'),
                                ('~~~', '```'), ('```', '```text'), ('~~~', '~~~\ttext')]:
            for trailing in ('', ' ', '\t', ' \t '):
                with self.subTest(opener=opener, invalid=invalid, trailing=trailing):
                    text = ('### Task 1: Done\n- [x] done\n' + opener + 'text\n'
                            + invalid + '\n### Task 99: Example\n- [ ] ignored\n')
                    self.plan.write_text(text)
                    before = self.plan.read_bytes(), self.progress.read_bytes()
                    for gate in (lambda: loop.next_task(self.plan, self.progress, 0),
                                 lambda: loop.check_move(self.plan, self.progress)):
                        with self.assertRaisesRegex(ValueError, 'unclosed code fence'):
                            gate()
                        self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)
                    self.plan.write_text(text + opener + opener[0] + trailing + '\n')
                    self.assertEqual([t['id'] for t in loop.tasks(self.plan)], ['Task 1'])
                    self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'tasks-complete')
                    self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')

    def test_list_styles_block_completion_and_preserve_move_coordinates(self):
        original_progress = self.progress.read_bytes()
        for marker in ('-', '*', '+', '1.', '0)', '123456789.'):
            for separator in (' ', '  ', '\t', ' \t  '):
                for newline in ('\n', '\r\n'):
                    with self.subTest(marker=marker, separator=separator, newline=repr(newline)):
                        prefix = '  ' + marker + separator
                        text = ('### Task 1: Final\n- [x] проверено\n'
                                + prefix + '[ ] required work\n'
                                + prefix + '[ ] move this plan to `completed/`\n')
                        before = text.replace('\n', newline).encode()
                        self.plan.write_bytes(before)
                        self.progress.write_bytes(original_progress)
                        parsed = loop.tasks(self.plan)[0]
                        self.assertEqual(parsed['checks'], [True, False, False])
                        self.assertEqual(parsed['check_texts'], ['проверено', 'required work',
                                                                 'move this plan to `completed/`'])
                        exact = before.decode()
                        self.assertEqual([exact[p] for p in parsed['check_positions']], ['x', ' ', ' '])
                        dispatched = loop.next_task(self.plan, self.progress, 0)
                        self.assertEqual(dispatched['state'], 'dispatch')
                        with self.assertRaisesRegex(ValueError, 'pending'):
                            loop.check_move(self.plan, self.progress)
                        with self.assertRaisesRegex(ValueError, 'only the final'):
                            loop.delegate_move(self.plan, self.progress, 'Task 1')
                        self.assertEqual(self.plan.read_bytes(), before)
                        done = before.replace(b'[ ] required', b'[x] required')
                        self.plan.write_bytes(done)
                        # Formatting and status are not semantic structure;
                        # changed text in any supported style must be detected.
                        self.plan.write_bytes(done.replace(b'required work', b'changed work'))
                        with self.assertRaisesRegex(ValueError, 'structure'):
                            loop.check_move(self.plan, self.progress)
                        self.plan.write_bytes(done)
                        loop.delegate_move(self.plan, self.progress, 'Task 1')
                        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'tasks-complete')
                        self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')
                        dest = self.work / 'completed' / self.plan.name
                        dest.parent.mkdir(exist_ok=True)
                        self.plan.rename(dest)
                        self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
                        self.assertEqual(dest.read_bytes(), done.replace(b'[ ] move', b'[x] move'))
                        dest.rename(self.plan)

    def test_unsupported_checkbox_candidates_fail_closed(self):
        for item in ('-[ ] work', '1.[ ] work', '1234567890. [ ] work',
                     '-\u00a0[ ] work', '\u00a0- [ ] work', '> - [ ] work',
                     '- [?] work', '*\t[] work', '1) [ ]', '+  [ ]\u00a0work'):
            with self.subTest(item=item):
                self.plan.write_text('### Task 1: Required\n- [x] done\n' + item + '\n')
                before = self.plan.read_bytes(), self.progress.read_bytes()
                for command in (['next', str(self.plan), str(self.progress), '0'],
                                ['check-move', str(self.plan), str(self.progress)]):
                    result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), *command],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('malformed checkbox', result.stderr)
                    self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_real_fence_openers_still_ignore_examples(self):
        for opener, closer in [('```python', '```'), ('````python', '`````'),
                               ('~~~python', '~~~~'), ('~~~python`info`', '~~~'),
                               ('~~~python`info', '~~~')]:
            with self.subTest(opener=opener):
                self.plan.write_text('### Task 1: Done\n- [x] done\n' + opener + '\n'
                                     '### Task 99: Example\n- [ ] ignored\n<!-- literal\n' + closer + '\n')
                self.assertEqual([task['id'] for task in loop.tasks(self.plan)], ['Task 1'])
                self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'tasks-complete')
                self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')

    def test_unsupported_fence_indentation_cannot_complete_pending_task(self):
        for indent in ('    ', '     ', '        ', '\t', ' \t', '\t   '):
            for marker in ('```', '~~~'):
                with self.subTest(indent=repr(indent), marker=marker):
                    self.plan.write_text('### Task 1: Done\n- [x] done\n' + indent + marker + '\n'
                                         '### Task 2: Required\n- [ ] required work\n' + indent + marker + '\n')
                    before = self.plan.read_bytes(), self.progress.read_bytes()
                    for command in (['next', str(self.plan), str(self.progress), '0'],
                                    ['check-move', str(self.plan), str(self.progress)]):
                        result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), *command],
                                                capture_output=True, text=True)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, '')
                        self.assertIn('unsupported fence indentation', result.stderr)
                        self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_fences_allow_zero_to_three_spaces_only(self):
        for spaces in range(4):
            for marker in ('```', '~~~'):
                for literal_indent in ('    ', '\t', ' \t'):
                    with self.subTest(spaces=spaces, marker=marker, literal_indent=repr(literal_indent)):
                        indent = ' ' * spaces
                        self.plan.write_text('### Task 1: Done\n- [x] done\n' + indent + marker + 'markdown\n'
                                             + literal_indent + marker + '\n'
                                             '### Task 99: Example\n- [ ] ignored\n' + indent + marker + '\n'
                                             '### Task 2: Required\n- [ ] required work\n')
                        self.assertEqual([t['id'] for t in loop.tasks(self.plan)], ['Task 1', 'Task 2'])
                        self.progress.write_text('')
                        result = loop.next_task(self.plan, self.progress, 0)
                        self.assertEqual((result['state'], result['task']), ('dispatch', 'Task 2'))
                        with self.assertRaisesRegex(ValueError, 'pending'):
                            loop.check_move(self.plan, self.progress)

    def test_invalid_backtick_info_fails_closed(self):
        for opener in ('```python`invalid', '````python```invalid'):
            with self.subTest(opener=opener):
                self.plan.write_text('### Task 1: Done\n- [x] done\n' + opener + '\n'
                                     '### Task 2: Required\n- [ ] required work\n```\n')
                before = self.plan.read_bytes(), self.progress.read_bytes()
                for gate in (lambda: loop.next_task(self.plan, self.progress, 0),
                             lambda: loop.check_move(self.plan, self.progress)):
                    with self.assertRaisesRegex(ValueError, 'unsupported inline code'):
                        gate()
                    self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_inline_code_comment_literals_cannot_hide_pending_work(self):
        original_progress = self.progress.read_bytes()
        for opening, closing in [('`<!--`', '`-->`'), ('``<!-- ` literal``', '``-->``'),
                                 ('```<!-- `` literal```', '```-->```')]:
            for newline in ('\n', '\r\n'):
                with self.subTest(opening=opening, newline=repr(newline)):
                    text = ('### Task 1: Final\n- [x] done\n'
                            'Literal ' + opening + '\n- [ ] implement required work\n'
                            'Literal ' + closing + '\n'
                            '<!-- actual comment\n- [ ] not a requirement\n-->\n'
                            '- [ ] move this plan to `completed/`\n')
                    before = text.replace('\n', newline).encode()
                    self.plan.write_bytes(before)
                    self.progress.write_bytes(original_progress)
                    parsed = loop.tasks(self.plan)[0]
                    self.assertEqual(parsed['checks'], [True, False, False])
                    for position in parsed['check_positions']:
                        self.assertIn(before.decode()[position], ' x')
                    self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'dispatch')
                    with self.assertRaisesRegex(ValueError, 'pending'):
                        loop.check_move(self.plan, self.progress)
                    with self.assertRaisesRegex(ValueError, 'only the final'):
                        loop.delegate_move(self.plan, self.progress, 'Task 1')
                    self.assertEqual(self.plan.read_bytes(), before)
                    # No move checkbox may mask the original completion bypass:
                    # the only pending requirement is between inline literals.
                    self.plan.write_bytes(before.replace(b'- [ ] move this plan to `completed/`', b''))
                    self.progress.write_bytes(original_progress)
                    self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'dispatch')
                    with self.assertRaisesRegex(ValueError, 'pending'):
                        loop.check_move(self.plan, self.progress)
                    # Once the real requirement is done, only the parser-scoped
                    # move checkbox changes, preserving literal/comment bytes.
                    completed = before.replace(b'[ ] implement', b'[x] implement')
                    self.plan.write_bytes(completed)
                    self.progress.write_bytes(original_progress)
                    loop.next_task(self.plan, self.progress, 0)
                    loop.delegate_move(self.plan, self.progress, 'Task 1')
                    dest = self.work / 'completed' / self.plan.name
                    dest.parent.mkdir(exist_ok=True)
                    self.plan.rename(dest)
                    self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
                    self.assertEqual(dest.read_bytes(), completed.replace(b'[ ] move', b'[x] move'))
                    dest.rename(self.plan)

    def test_escaped_html_opener_is_literal_with_odd_backslashes(self):
        original_progress = self.progress.read_bytes()
        for count in (1, 2, 3, 4):
            for newline in ('\n', '\r\n'):
                with self.subTest(count=count, newline=repr(newline)):
                    text = ('### Task 1: Final\n- [x] done\n' + '\\' * count + '<!--\n'
                            '- [ ] required work\n\\-->\n')
                    self.plan.write_bytes(text.replace('\n', newline).encode())
                    self.progress.write_bytes(original_progress)
                    parsed = loop.tasks(self.plan)[0]
                    self.assertEqual(parsed['checks'], [True, False] if count % 2 else [True])
                    if count % 2:
                        position = parsed['check_positions'][1]
                        self.assertEqual(self.plan.read_bytes().decode()[position], ' ')
                        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'dispatch')
                        with self.assertRaisesRegex(ValueError, 'pending'):
                            loop.check_move(self.plan, self.progress)
                    else:
                        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'tasks-complete')
                        self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')

    def test_inline_code_cannot_cross_paragraph_or_task_boundaries(self):
        original_progress = self.progress.read_bytes()
        # Previously the first backtick paired with Task 2's backtick, shielding
        # the real comment opener and activating the fence inside that comment.
        bypass = ('### Task 1: Done\n- [x] done\nLiteral `\n\n<!--\n```\n-->\n'
                  '### Task 2: Required\n- [ ] required work\nLiteral `\n```\n')
        for text in (bypass, bypass.replace('`\n\n<!--', '`\n<!--'),
                     '### Task 1: Done\n- [x] done `\n\nLiteral `\n',
                     '### Task 1: Done\n- [x] done `\n### Task 2: Required\n- [ ] work `\n'):
            with self.subTest(text=text):
                self.plan.write_text(text)
                self.progress.write_bytes(original_progress)
                before = self.plan.read_bytes(), self.progress.read_bytes()
                for gate in (lambda: loop.next_task(self.plan, self.progress, 0),
                             lambda: loop.check_move(self.plan, self.progress)):
                    with self.assertRaisesRegex(ValueError, 'inline code'):
                        gate()
                    self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)
                result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), 'next',
                                         str(self.plan), str(self.progress), '0'], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('unsupported inline code', result.stderr)
                self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_escaped_backticks_and_comment_fence_order(self):
        self.plan.write_text('### Task 1: Required\n- [x] done\nLiteral \\`\n'
                             '<!-- backticks ` are literal here\n```\n\\-->\n'
                             '- [ ] required work\n'
                             '```markdown\n\\<!--\n### Task 99: Example\n- [ ] example\n```\n')
        parsed = loop.tasks(self.plan)
        self.assertEqual([task['id'] for task in parsed], ['Task 1'])
        self.assertEqual(parsed[0]['checks'], [True, False])
        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['task'], 'Task 1')
        with self.assertRaisesRegex(ValueError, 'pending'):
            loop.check_move(self.plan, self.progress)

    def test_html_comments_ignore_tasks_checks_and_preserve_completion_coordinates(self):
        original_progress = self.progress.read_bytes()
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                text = ('<!--\n### Task 1: duplicate example\n- [ ] ignored\n```\n-->\n'
                        '```markdown\n<!-- literal fence comment\n### Task 99: example\n- [ ] ignored\n```\n'
                        '### Task 1: Final\n<!--\n## Hidden heading\n- [?] hidden malformed check\n-->\n'
                        '- [x] проверено <!-- invisible -->\n'
                        '<!-- inline -->  * [ ] move this plan to `completed/`\n'
                        '<!-- - [ ] hidden -->\n')
                before = text.replace('\n', newline).encode()
                self.plan.write_bytes(before)
                self.progress.write_bytes(original_progress)
                parsed = loop.tasks(self.plan)
                self.assertEqual([t['id'] for t in parsed], ['Task 1'])
                self.assertEqual(parsed[0]['checks'], [True, False])
                self.assertEqual(parsed[0]['check_texts'][-1], 'move this plan to `completed/`')
                loop.next_task(self.plan, self.progress, 0)
                loop.delegate_move(self.plan, self.progress, 'Task 1')
                self.assertEqual(self.plan.read_bytes(), before)
                dest = self.work / 'completed' / self.plan.name
                dest.parent.mkdir(exist_ok=True)
                self.plan.rename(dest)
                self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
                self.assertEqual(dest.read_bytes(), before.replace(b'  * [ ]', b'  * [x]', 1))
                dest.rename(self.plan)
        self.plan.write_text('### Task 1: Valid\n- [x] done\n<!-- never closed\n- [ ] hidden\n')
        before = self.plan.read_bytes(), self.progress.read_bytes()
        result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), 'next',
                                 str(self.plan), str(self.progress), '0'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unclosed HTML comment', result.stderr)
        self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)

    def test_resume_limit_and_structure_change(self):
        loop.next_task(self.plan, self.progress, 0)
        before = self.progress.read_bytes()
        self.init()
        self.assertEqual(self.progress.read_bytes(), before)
        self.assertEqual(loop.next_task(self.plan, self.progress, 0)["state"], "failed")
        self.assertNotEqual(self.init(self.work / "different.md", check=False).returncode, 0)
        self.plan.write_text(self.text.replace("Produce", "Changed"))
        with self.assertRaisesRegex(ValueError, "structure"):
            loop.next_task(self.plan, self.progress, 2)

    def test_fifty_dispatch_limit(self):
        self.plan.write_text("\n".join(f"### Task {i}: T\n- [ ] item" for i in range(1, 52)))
        for i in range(1, 51):
            self.assertEqual(loop.next_task(self.plan, self.progress, 0)["task"], f"Task {i}")
            self.plan.write_text(self.plan.read_text().replace("[ ]", "[x]", 1))
        self.assertEqual(loop.next_task(self.plan, self.progress, 0)["reason"], "50 dispatch limit")

    def test_all_gates_reject_invalid_dispatch_state_without_writes(self):
        self.plan.write_text('### Task 1: Final\n- [x] tested\n'
                             '- [ ] move this plan to `completed/`\n')
        record = loop.next_task(self.plan, self.progress, 0)
        record = {key: record[key] for key in ('plan', 'task', 'attempt', 'structure')}
        for case in ('corrupt', 'foreign', 'stale', 'missing-fields', 'wrong-type'):
            for gate in ('next', 'check-move', 'delegate-move', 'complete-move'):
                with self.subTest(case=case, gate=gate):
                    bad = dict(record)
                    if case == 'foreign':
                        bad['plan'] = str(self.work / 'foreign.md')
                    elif case == 'stale':
                        bad['structure'] = 'outdated'
                    elif case == 'missing-fields':
                        del bad['task']
                    elif case == 'wrong-type':
                        bad = []
                    payload = 'not JSON' if case == 'corrupt' else json.dumps(bad)
                    self.progress.write_text('[dispatch] ' + payload + '\n')
                    # All checks completed is not permission to bypass validation.
                    self.plan.write_text('### Task 1: Final\n- [x] tested\n'
                                         '- [x] move this plan to `completed/`\n')
                    dest = self.work / 'completed' / self.plan.name
                    args = [gate, str(self.plan), str(self.progress)]
                    if gate == 'next':
                        args.append('0')
                    elif gate == 'delegate-move':
                        args.append('Task 1')
                    elif gate == 'complete-move':
                        dest.parent.mkdir(exist_ok=True)
                        self.plan.rename(dest)
                        args.append(str(dest))
                    target = dest if gate == 'complete-move' else self.plan
                    before = (target.read_bytes(), self.progress.read_bytes())
                    result = subprocess.run(['python3', str(SCRIPTS / 'task-loop.py'), *args],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('task-loop:', result.stderr)
                    self.assertEqual((target.read_bytes(), self.progress.read_bytes()), before)
                    if gate == 'complete-move':
                        dest.rename(self.plan)

    def test_dispatch_hash_tracks_checkbox_content_and_order_not_status(self):
        self.text = self.text.replace('- [ ] produce', '- [ ] produce\n- [ ] verify')
        self.plan.write_text(self.text)
        loop.next_task(self.plan, self.progress, 0)
        for changed in (self.text.replace('produce', 'different requirement'),
                        self.text.replace('- [ ] produce\n- [ ] verify', '- [ ] verify\n- [ ] produce'),
                        self.text.replace('- [ ] produce', '- [ ] extra\n- [ ] produce')):
            with self.subTest(changed=changed):
                self.plan.write_text(changed.replace('[ ]', '[x]'))
                with self.assertRaisesRegex(ValueError, 'structure'):
                    loop.next_task(self.plan, self.progress, 0)
                with self.assertRaisesRegex(ValueError, 'structure'):
                    loop.check_move(self.plan, self.progress)
        self.plan.write_text(self.text.replace('[ ]', '[X]'))
        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['state'], 'tasks-complete')
        self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')

    def test_move_helper_rejects_corrupt_dispatch_before_moving(self):
        self.plan.write_text(self.text.replace('[ ]', '[x]'))
        self.progress.write_text('[dispatch] not JSON\n')
        before = (self.plan.read_bytes(), self.progress.read_bytes())
        result = subprocess.run(['bash', str(SCRIPTS / 'move-plan.sh'), str(self.plan), str(self.progress)],
                                cwd=self.work, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('task-loop:', result.stderr)
        self.assertNotIn('"state": "ready"', result.stdout)
        self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)
        self.assertFalse((self.work / 'completed' / self.plan.name).exists())

    def test_render_values_are_data_and_required(self):
        template = self.work / "prompt.md"
        template.write_text("{{WORKING_DIRECTORY}}\n{{USER_RULES}}")
        context = self.work / "context.json"
        context.write_text(json.dumps({"WORKING_DIRECTORY": str(self.work)}))
        with self.assertRaisesRegex(ValueError, "missing"):
            loop.render(template, context)
        data = {"WORKING_DIRECTORY": str(self.work), "USER_RULES": '$(touch NEVER) `false` {{NOT_A_SLOT}}'}
        context.write_text(json.dumps(data))
        self.assertEqual(loop.render(template, context), str(self.work) + "\n" + data["USER_RULES"])
        data["WORKING_DIRECTORY"] = "relative"
        context.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "absolute"):
            loop.render(template, context)
        context.write_text("[]")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            loop.render(template, context)
        template.write_text("${CLAUDE_PLUGIN_ROOT}")
        with self.assertRaisesRegex(ValueError, "legacy"):
            loop.render(template, context)
        self.assertFalse((self.work / "NEVER").exists())

    def test_standard_make_plan_delegates_move_durably_and_completes_after_move(self):
        self.plan.write_text('# Plan\n### Task 1: Implement\n- [x] tested\n'
                             '### Task 2: [Final] Update documentation\n- [x] update README.md if needed\n'
                             '- [x] update applicable AGENTS.md if new patterns discovered\n'
                             '- [ ] move this plan to `completed/`\n')
        self.assertEqual(loop.next_task(self.plan, self.progress, 0)['task'], 'Task 2')
        loop.delegate_move(self.plan, self.progress, 'Task 2')
        result = loop.next_task(self.plan, self.progress, 0)
        self.assertEqual(result['state'], 'tasks-complete')
        self.assertTrue(result['completion_move_pending'])
        self.assertIn('[ ] move this plan', self.plan.read_text())
        # Reload durable state; no retry consumed and no early checkbox completion.
        self.assertEqual(loop.next_task(self.plan, self.progress, 0), result)
        dest = self.work / 'completed' / self.plan.name
        dest.parent.mkdir()
        with self.assertRaises(OSError):
            loop.complete_move(self.plan, self.progress, dest)
        self.plan.rename(dest)
        self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
        self.assertIn('[x] move this plan', dest.read_text())
        self.assertIn('[completion-move-fulfilled]', self.progress.read_text())

    def test_cannot_delegate_arbitrary_or_stale_pending_work(self):
        with self.assertRaisesRegex(ValueError, 'move-only'):
            loop.delegate_move(self.plan, self.progress, 'Iteration 2')
        self.plan.write_text(self.text + '- [ ] move this plan to `completed/`\n')
        with self.assertRaisesRegex(ValueError, 'only the final'):
            loop.delegate_move(self.plan, self.progress, 'Iteration 2')
        self.plan.write_text(self.plan.read_text().replace('[ ] produce', '[x] produce').replace('[ ] consume', '[x] consume'))
        loop.delegate_move(self.plan, self.progress, 'Iteration 2')
        self.plan.write_text(self.plan.read_text().replace('completed/', 'elsewhere/'))
        with self.assertRaisesRegex(ValueError, 'destination|stale'):
            loop.next_task(self.plan, self.progress, 1)

    def test_move_updates_only_parsed_checkbox_preserving_exact_bytes(self):
        original_progress = self.progress.read_bytes()
        for newline in ('\n', '\r\n'):
            for fence in ('```markdown', '~~~~markdown'):
                with self.subTest(newline=repr(newline), fence=fence):
                    move = '- [ ] move this plan to `completed/`'
                    closing = fence[:3] if fence.startswith('`') else '~~~~'
                    text = ('# План — пример\n' + move + '\n' + fence + '\n'
                            '### Task 99: Example\n' + move + '\n' + closing + '\n'
                            '### Task 1: Final\n- [x] проверено\n  * [ ] move this plan to `completed/`\n'
                            + fence + '\n' + move + '\n' + closing + '\n'
                            '## Outside tasks\n' + move)
                    before = text.replace('\n', newline).encode()
                    expected = before.replace(b'  * [ ]', b'  * [x]', 1)
                    self.plan.write_bytes(before)
                    self.progress.write_bytes(original_progress)
                    positions = loop.tasks(self.plan)[0]['check_positions']
                    exact_text = before.decode()
                    self.assertEqual([exact_text[p] for p in positions], ['x', ' '])
                    self.assertEqual(positions[-1], exact_text.index('  * [ ]') + len('  * ['))
                    loop.next_task(self.plan, self.progress, 0)
                    loop.delegate_move(self.plan, self.progress, 'Task 1')
                    self.assertEqual(loop.check_move(self.plan, self.progress)['state'], 'ready')
                    dest = self.work / 'completed' / self.plan.name
                    dest.parent.mkdir(exist_ok=True)
                    self.plan.rename(dest)
                    self.assertEqual(loop.tasks(dest)[0]['check_positions'], positions)
                    self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
                    self.assertEqual(dest.read_bytes(), expected)
                    self.assertTrue(all(loop.tasks(dest)[0]['checks']))
                    dest.rename(self.plan)

    def test_delegation_destination_is_checked_before_move_and_fulfillment(self):
        valid = '### Task 1: Final\n- [x] tested\n- [ ] move this plan to `completed/`\n'
        original_progress = self.progress.read_bytes()
        for destination in ('docs/archive/', 'elsewhere/completed/', '../completed/'):
            with self.subTest(destination=destination):
                self.plan.write_text(valid.replace('completed/', destination))
                self.progress.write_bytes(original_progress)
                before = self.plan.read_bytes(), self.progress.read_bytes()
                with self.assertRaisesRegex(ValueError, 'destination'):
                    loop.delegate_move(self.plan, self.progress, 'Task 1')
                result = subprocess.run(['bash', str(SCRIPTS / 'move-plan.sh'),
                                         str(self.plan), str(self.progress)],
                                        cwd=self.work, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.plan.read_bytes(), self.progress.read_bytes()), before)
                self.assertFalse((self.work / 'completed').exists())
                # A delegation persisted by the old implementation must not
                # fulfill an archive request after moving to completed/ either.
                parsed = loop.tasks(self.plan)
                legacy = {'plan': str(self.plan.resolve()), 'task': 'Task 1', 'index': 1,
                          'text': parsed[-1]['check_texts'][-1],
                          'structure': [(t['id'], t['title'], t['check_texts']) for t in parsed]}
                self.progress.write_text('[completion-move-delegated] ' + json.dumps(legacy) + '\n')
                dest = self.work / 'completed' / self.plan.name
                dest.parent.mkdir()
                self.plan.rename(dest)
                before = dest.read_bytes(), self.progress.read_bytes()
                with self.assertRaisesRegex(ValueError, 'destination'):
                    loop.complete_move(self.plan, self.progress, dest)
                self.assertEqual((dest.read_bytes(), self.progress.read_bytes()), before)
                dest.rename(self.plan)
                dest.parent.rmdir()
        for destination in ('completed/', str(self.work / 'completed') + '/'):
            with self.subTest(valid_destination=destination):
                self.plan.write_text(valid.replace('completed/', destination))
                self.progress.write_bytes(original_progress)
                self.assertEqual(loop.delegate_move(self.plan, self.progress, 'Task 1')['state'], 'delegated')
                dest = self.work / 'completed' / self.plan.name
                dest.parent.mkdir(exist_ok=True)
                self.plan.rename(dest)
                progress_before = self.progress.read_bytes()
                other = self.work / 'archive' / self.plan.name
                other.parent.mkdir(exist_ok=True)
                dest.rename(other)
                with self.assertRaisesRegex(ValueError, 'destination'):
                    loop.complete_move(self.plan, self.progress, other)
                self.assertEqual(self.progress.read_bytes(), progress_before)
                self.assertIn('[ ] move', other.read_text())
                other.rename(dest)
                self.assertEqual(loop.complete_move(self.plan, self.progress, dest)['state'], 'fulfilled')
                dest.rename(self.plan)

    def test_playbook_gates_block_unvalidated_or_other_pending_work(self):
        valid = ('### Task 1: Implement\n- [x] tested\n### Task 2: Final\n'
                 '- [x] docs\n- [ ] move this plan to `completed/`\n')
        self.plan.write_text(valid)
        unrecorded = self.progress.read_text()
        loop.delegate_move(self.plan, self.progress, 'Task 2')
        delegated = self.progress.read_text()
        for playbook in ('task-loop.md', 'review-phases.md'):
            for case in ('no-delegation', 'other-pending', 'stale', 'foreign', 'corrupt', 'malformed', 'missing'):
                with self.subTest(playbook=playbook, case=case):
                    self.plan.write_text(valid)
                    self.progress.write_text(delegated)
                    if case == 'no-delegation':
                        self.progress.write_text(unrecorded)
                    elif case == 'other-pending':
                        self.plan.write_text(valid.replace('[x] tested', '[ ] tested'))
                    elif case == 'stale':
                        self.plan.write_text(valid.replace('completed/', 'elsewhere/'))
                    elif case == 'foreign':
                        self.progress.write_text(delegated.replace(str(self.plan), str(self.work / 'foreign.md')))
                    elif case == 'corrupt':
                        self.progress.write_text(delegated + '[completion-move-delegated] not JSON\n')
                    elif case == 'malformed':
                        self.plan.write_text('### Task 1: Empty\n')
                    else:
                        self.plan.unlink()
                    result = self.playbook_move_gate(playbook)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('task-loop:', result.stderr)
            # Ordinary completed plans still pass without delegation.
            self.plan.write_text(valid.replace('[ ]', '[x]'))
            self.progress.write_text(unrecorded)
            result = self.playbook_move_gate(playbook)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'state': 'ready', 'completion_move_pending': False})

    def test_move_helper_commits_fulfilled_delegation_preserving_foreign_index(self):
        env = {**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=self.work, env=env, text=True).strip()
        git('init', '-qb', 'main')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@invalid')
        self.plan.write_text('### Task 1: Implement\n- [x] tested\n'
                             '### Task 2: [Final] Update documentation\n'
                             '- [x] update README.md if needed\n'
                             '- [x] update applicable AGENTS.md if new patterns discovered\n'
                              '- [ ] move this plan to `completed/`\n')
        self.plan.write_text(self.plan.read_text() +
                             '```markdown\n- [ ] move this plan to `completed/`\n```\n')
        git('add', self.plan.name)
        git('commit', '-qm', 'plan')
        (self.work / 'foreign').write_text('staged foreign work')
        git('add', 'foreign')
        foreign = git('diff', '--cached')
        argv = ['bash', str(SCRIPTS / 'move-plan.sh'), str(self.plan), str(self.progress)]
        refused = subprocess.run(argv, cwd=self.work, env=env, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertTrue(self.plan.is_file())
        self.assertIn('pending', refused.stderr)
        dispatched = loop.next_task(self.plan, self.progress, 0)
        self.assertEqual((dispatched['state'], dispatched['task']), ('dispatch', 'Task 2'))
        loop.delegate_move(self.plan, self.progress, 'Task 2')
        # Standard make orchestration: post-child admission must not retry the
        # sole remaining move. Review/finalize/stats here are explicit fixture
        # events, not a claim of model reviews or live API coverage.
        post_child = self.playbook_move_gate('task-loop.md')
        self.assertEqual(post_child.returncode, 0, post_child.stderr)
        self.assertEqual(json.loads(post_child.stdout), {'state': 'ready', 'completion_move_pending': True})
        admitted = loop.next_task(self.plan, self.progress, 0)
        self.assertEqual(admitted['state'], 'tasks-complete')
        self.assertEqual(admitted['total'], 2)
        self.assertTrue(admitted['completion_move_pending'])
        dispatches = [line for line in self.progress.read_text().splitlines() if line.startswith('[dispatch] ')]
        self.assertEqual(len(dispatches), 1)  # no retry even with retries=0
        pending = self.plan.read_bytes()
        for phase in ('comprehensive', 'smells', 'external', 'critical', 'finalize', 'stats'):
            subprocess.run(['bash', str(SCRIPTS / 'append-progress.sh'), str(self.progress),
                            'fixture phase: ' + phase], check=True, capture_output=True)
            self.assertEqual(self.plan.read_bytes(), pending)
        completion = self.playbook_move_gate('review-phases.md')
        self.assertEqual(completion.returncode, 0, completion.stderr)
        self.assertEqual(json.loads(completion.stdout), {'state': 'ready', 'completion_move_pending': True})
        moved = subprocess.run(argv, cwd=self.work, env=env, capture_output=True, text=True)
        self.assertEqual(moved.returncode, 0, moved.stderr)
        dest = self.work / 'completed' / self.plan.name
        self.assertIn('[x] move this plan', dest.read_text())
        self.assertIn('[x] move this plan', git('show', 'HEAD:completed/' + self.plan.name))
        self.assertEqual(git('diff', '--cached'), foreign)
        head = git('rev-parse', 'HEAD')
        self.assertEqual(subprocess.run(argv, cwd=self.work, env=env, capture_output=True).returncode, 0)
        self.assertEqual(git('rev-parse', 'HEAD'), head)

    def test_missing_plan_and_corrupt_progress_exit_nonzero(self):
        self.progress.write_text('[dispatch] not JSON\n')
        result = subprocess.run(["python3", str(SCRIPTS / "task-loop.py"), "next",
                                 str(self.plan), str(self.progress), "1"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_bundled_prompt_contract_and_symlink_helpers(self):
        import re
        template = SCRIPTS.parent / "references/prompts/task.md"
        required = set(re.findall(r"\{\{([A-Z_]+)\}\}", template.read_text()))
        values = {key: "none" for key in required}
        for key in required:
            if key.endswith(("_PATH", "_DIR", "_DIRECTORY")) or key == "RESOLVE_SCRIPT":
                values[key] = str(self.work / key)
        context = self.work / "context.json"
        context.write_text(json.dumps(values))
        rendered = loop.render(template, context)
        self.assertNotRegex(rendered, r"\{\{[A-Z_]+\}\}")
        self.assertIn(str(self.work / "PLAN_FILE_PATH"), rendered)
        # A script symlink must locate its sibling VCS dispatcher in source.
        linked = self.work / "branch helper"
        linked.symlink_to(SCRIPTS / "create-branch.sh")
        result = subprocess.run(["bash", str(linked), "--print-name", "20261103-feature.md"],
                                 capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "feature\n")


unittest.main(verbosity=2)
