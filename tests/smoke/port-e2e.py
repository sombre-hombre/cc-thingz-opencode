#!/usr/bin/env python3
"""Opt-in connected Task15 chain on authorized active service. No human UI.

Each completed stage persists before the next; --resume-artifacts waits for the
same session, validates and continues, never repeats an admitted model request.
Only the graphical executable is replaced: real revdiff runs in a controlled PTY.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api, wait_idle

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-current-model', action='store_true', required=True)
    parser.add_argument('--parent', required=True)
    parser.add_argument('--resume-artifacts', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = args.resume_artifacts or Path(tempfile.mkdtemp(prefix='cc-thingz-port-e2e.', dir='/tmp/opencode'))
    print('Artifacts:', run, flush=True)
    statefile = run / 'state.json'
    state = json.loads(statefile.read_text()) if statefile.exists() else {}
    source, bundle = run / 'source with spaces', run / 'bundle with spaces'
    plan = source / 'docs/plans/positive count.md'
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', PYTHONDONTWRITEBYTECODE='1')

    def save(name, data):
        (run / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')

    def persist():
        save('state', state)

    def git(directory, *argv):
        return subprocess.check_output(['git', '-C', str(directory), *argv], env=env, text=True)

    wt = load(root / 'plugins/planning/skills/exec/scripts/worktree.py', 'wt')
    sid = state.get('sessionID')

    def turn(name, route, body):
        if name not in state:
            # An uncertain transport failure is a blocker; never auto-resubmit.
            state[name] = 'admission-attempted'
            persist()
            api('POST', f'/api/session/{sid}/{route}', body)
            state[name] = 'admitted'
            persist()
        assert state[name] != 'admission-attempted', 'inspect uncertain admission before retry: ' + name
        wait_idle(api, save, sid, 2400)
        context = api('GET', f'/api/session/{sid}/context')
        save(name + '-context', context)
        errors = [m['error'] for m in context['data'] if m.get('type') == 'idle' and m.get('error')]
        assert not errors, errors
        state[name] = 'idle'
        persist()
        return context

    def review(name, mode):
        if name in state:
            return json.loads((run / (name + '.json')).read_text())
        output, status = run / (name + '.md'), run / (name + '.json')
        proc = subprocess.run(['bash', str(bundle / 'plugins/planning/scripts/launch-plan-review.sh'), str(plan),
            '--terminal', 'kitty-window', '--wayland-display', 'fixture-no-display', '--xdg-runtime-dir', str(run),
            '--output', str(output), '--status', str(status), '--exit-code-on-annotations', '--timeout', '25'],
            env=dict(env, PATH=str(run / 'bin') + ':' + env['PATH'], PROBE=mode,
                     PROBE_ROW='1', SCREEN=str(run / (name + '.screen')), TERM='xterm-256color'),
            capture_output=True, timeout=35)
        data = json.loads(status.read_text())
        assert proc.returncode == 0 and data['state'] == ('annotations' if mode == 'annotation' else 'needs-confirmation'), data
        state[name] = 'complete'
        persist()
        return data

    try:
        if not sid:
            parent = api('GET', f'/api/session/{args.parent}')['data']
            model = parent['model']
            assert model == {'providerID': 'openai', 'id': 'gpt-6.1-sol', 'variant': 'medium'}
            save('authorization', {'parentID': args.parent, 'parent_location': parent['location'], 'model': model})
            for name in ('plugins', 'scripts', 'commands'):
                shutil.copytree(root / name, bundle / name)
            manifest = json.loads((root / 'install-manifest.json').read_text())
            for group in ('skills', 'commands', 'agents'):
                for entry in manifest[group]:
                    target = source / '.opencode' / entry['target']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(bundle / entry['source'])
            (source / 'opencode.json').write_text(json.dumps({'$schema': 'https://opencode.ai/config.json',
                'snapshots': False, 'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]}) + '\n')
            (source / 'AGENTS.md').write_text('Only this isolated fixture. No push, publication, global config or credentials access. Python stdlib only. Use PYTHONDONTWRITEBYTECODE=1 for Python tests. Preserve unrelated files.\n')
            (source / 'counter.py').write_text('def parse_count(value):\n    count = int(value)\n    if count < 0:\n        raise ValueError("positive count required")\n    return count\n')
            (source / 'README.md').write_text('# Count parser\nUse python3 -m unittest -v.\n')
            # Committed project override must still resolve after native session_move.
            override = source / '.opencode/exec-plan/agents/documentation.txt'
            override.parent.mkdir(parents=True)
            override.write_text((bundle / 'plugins/planning/skills/exec/references/agents/documentation.txt').read_text()
                                + '\nReport the project override marker DOC-OVERRIDE-15 in your final response.\n')
            git(source, 'init', '-qb', 'main')
            git(source, 'config', 'user.name', 'Port E2E')
            git(source, 'config', 'user.email', 'smoke@example.invalid')
            git(source, 'add', '.')
            git(source, 'commit', '-qm', 'fixture baseline')
            git(source, 'switch', '-qc', 'source-feature')
            sid = api('POST', '/api/session', {'title': 'Task15 connected brainstorm to completion', 'agent': 'build',
                'location': {'directory': str(source)}, 'model': model,
                'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]})['data']['id']
            state['sessionID'] = sid
            persist()
            deadline = time.monotonic() + 30
            while True:
                skills = api('GET', '/api/skill?' + urlencode({'location[directory]': str(source)}))['data']
                if len(skills) >= 17:
                    break
                assert time.monotonic() < deadline, 'registry activation timeout'
                time.sleep(.2)
            save('registry-skills', skills)
            for entry in manifest['skills']:
                found = [s for s in skills if s['id'] == entry['id']]
                assert len(found) == 1 and Path(found[0]['path']).resolve() == bundle / entry['source'] / 'SKILL.md', entry
            commands = api('GET', '/api/command?' + urlencode({'location[directory]': str(source)}))['data']
            save('registry-commands', commands)
            # Graphical executable fixture delegates to real worker/revdiff in PTY.
            driver = (root / 'tests/smoke/no-tmux-plan-review.py').read_text().replace(
                "b'Last line marker' in screen", "b'Count parser' in screen").replace(
                "b'No-tmux contract annotation'", "b'Add acceptance marker ZERO-REJECTED-15: zero raises ValueError.'")
            (run / 'pty-driver.py').write_text(driver)
            (run / 'bin').mkdir()
            terminal = run / 'bin/kitty'
            terminal.write_text('#!' + sys.executable + '\nimport runpy,sys\nsys.argv.insert(1,"--pty-terminal")\nrunpy.run_path('
                                + repr(str(run / 'pty-driver.py')) + ',run_name="__main__")\n')
            terminal.chmod(0o755)
        auth = json.loads((run / 'authorization.json').read_text())
        assert auth['parentID'] == args.parent and sid != args.parent
        turn('planning', 'prompt', {'text': '@brainstorm All design answers already agreed: goal reject zero/negative counts in counter.parse_count, '
            'preserve positive integers and int conversion/ValueError on invalid input. Scope counter.py, test_counter.py, README.md only. '
            'Selected approach int conversion then strict >0 validation; no library/new parser, stdlib unittest Regular testing. '
            'Brainstorm phases1–3 validated; phase4 choice Write plan. Load make in THIS session, do not repeat questions. '
            f'Exactly two small tasks: Task1 fix parser and boundary/error tests; Task2 document its verified behavior after Task1. Plan at {plan}. '
            'Title Count parser. Create plan only, Done and scoped plan commit; no auto review, no interactive review yet, no implementation. '
            'No custom rules. No push/config changes. Keep exactly two tasks; include standard make final checkbox '
            '"move this plan to `docs/plans/completed/`" as the LAST checkbox of Task2. '
            'It stays pending through durable task-loop delegate-move until exec completion, not another task.',
            'skills': [{'id': 'brainstorm', 'mention': {'start': 0, 'end': 11, 'text': '@brainstorm'}}]})
        assert plan.is_file() or state.get('execution')
        if not state.get('execution'):
            text = plan.read_text()
            assert len(re.findall(r'^### Task \d+:', text, re.M)) == 2, text
            assert '- [ ] move this plan to `docs/plans/completed/`' in text, text
            annotation = review('review-first', 'annotation')
            assert annotation['revdiff_exit'] == 10
            turn('revision', 'command', {'name': 'review-plan', 'text': f'{plan} review-only. Controlled automated PTY review ALREADY ran, no human. '
                f'Read complete status {run / "review-first.json"} and annotations {run / "review-first.md"}; check snapshot hash/path. '
                'Selected fix explicitly approved for this automated scenario: append exact acceptance line "ZERO-REJECTED-15: zero raises ValueError." '
                'Keep two tasks/previous decisions. Read back and scoped commit only this plan. Stop; harness will reopen real revdiff. '
                'Do not launch UI or exec, no questions.'})
            assert 'ZERO-REJECTED-15: zero raises ValueError.' in plan.read_text()
            empty = review('review-second', 'empty')
            assert empty['state'] == 'needs-confirmation'
            if 'before' not in state:
                (source / 'foreign staged.txt').write_text('PRESERVE staged\n')
                git(source, 'add', 'foreign staged.txt')
                (source / 'foreign untracked.txt').write_text('PRESERVE untracked\n')
                save('before', wt.snapshot(source))
                state['before'] = True
                persist()
        context = turn('execution', 'command', {'name': 'exec', 'text': f'Review complete: explicit automated test-driver choice AFTER reopening. '
            f'Read {run / "review-second.json"}; empty revdiff is needs-confirmation, this message supplies completion, not exit0 alone. '
            f'Execute full {plan}, previously agreed design/2 tasks; isolation choice MOVE TO WORKTREE from actual source HEAD. '
            f'Use project exec from {bundle}, native session_move on THIS session only. Root ID {sid}. '
            'No questions, no repeated agreed decisions. Do not edit implementation as parent; fresh general tasks strictly sequential then MAIN fanout. '
            'Authorized test-run settings: task_retries=1, review_iterations=1, external_review_iterations=1, finalize_enabled=true, '
            'external_review_cmd empty (real Codex, timeout90s). Do not read/change global settings/overrides; no custom rules. '
            'Preserve source dirty files and branch exactly. Resolve committed project documentation override again AFTER move and deliver full override to child. '
            f'Keep all run artifacts/rendered prompts/external output below {run / "exec"}; '
            f'use progress path {run / "exec/progress.txt"}; report absolute paths. '
            'All phases: five parallel comprehensive specialists (fixer only on real findings), smells, real external review, two parallel final critical, '
            'safe verify-only finalizer (NO rewrite/fetch/squash/push consent), API stats child/full verbatim report, sole move completed plan scoped commit. '
            'Helpers/resources must use canonical bundle paths after move. Verify source guard. PYTHONDONTWRITEBYTECODE=1 tests.'})
        work = Path(api('GET', f'/api/session/{sid}')['data']['location']['directory'])
        assert work != source
        before = json.loads((run / 'before.json').read_text())
        assert wt.snapshot(source) == before
        assert not (source / 'test_counter.py').exists()
        completed = work / 'docs/plans/completed/positive count.md'
        progress = run / 'exec/progress.txt'
        assert completed.is_file() and '[ ]' not in completed.read_text()
        assert '[completion-move-delegated] ' in progress.read_text()
        assert '[completion-move-fulfilled] ' in progress.read_text()
        assert 'ZERO-REJECTED-15' in completed.read_text()
        subprocess.run(['python3', '-m', 'unittest', '-v'], cwd=work, env=env, check=True)
        probe = subprocess.run(['python3', '-c', 'from counter import parse_count\nassert parse_count("3")==3\ntry: parse_count(0)\nexcept ValueError: pass\nelse: raise AssertionError("zero accepted")'], cwd=work, env=env, capture_output=True, text=True)
        assert probe.returncode == 0, probe.stderr
        calls = [c for m in context['data'] for c in m.get('content', []) if c.get('type') == 'tool']
        children_calls = [c for c in calls if c['name'] == 'subagent']
        assert len(children_calls) >= 12, 'missing phases'
        for c in children_calls:
            assert c['state']['status'] == 'completed', c
            assert c['state']['input']['agent'] == 'general' and not c['state']['input'].get('sessionID')
        child_ids = [c['state']['metadata']['sessionID'] for c in children_calls]
        assert len(child_ids) == len(set(child_ids)), 'reused child context'
        tasks = [c for c in children_calls if re.search(r'Task [12]', c['state']['input']['description'])]
        assert len(tasks) == 2 and tasks[0]['time']['completed'] <= tasks[1]['time']['ran']
        reviews = [c for c in children_calls if c['time']['ran'] >= tasks[-1]['time']['completed']][:5]
        assert len(reviews) == 5 and max(c['time']['ran'] for c in reviews) < min(c['time']['completed'] for c in reviews)
        smells = [c for c in children_calls if 'smell' in c['state']['input']['description'].lower()]
        critical = [c for c in children_calls if 'final critical' in c['state']['input']['description'].lower()]
        finalizers = [c for c in children_calls if 'finaliz' in c['state']['input']['description'].lower()]
        stats_calls = [c for c in children_calls if 'stats' in c['state']['input']['description'].lower()]
        assert len(smells) == 1 and len(critical) == 2 and len(finalizers) == 1 and len(stats_calls) == 1
        assert smells[0]['time']['ran'] >= max(c['time']['completed'] for c in reviews)
        assert max(c['time']['ran'] for c in critical) < min(c['time']['completed'] for c in critical)
        assert min(c['time']['ran'] for c in critical) >= smells[0]['time']['completed']
        assert finalizers[0]['time']['ran'] >= max(c['time']['completed'] for c in critical)
        assert stats_calls[0]['time']['ran'] >= finalizers[0]['time']['completed']
        stats_text = '\n'.join(p['text'] for p in stats_calls[0]['state'].get('content', []) if p.get('type') == 'text')
        stats_text = re.sub(r'^<subagent[^>]*>\n|\n</subagent>$', '', stats_text)
        parent_text = '\n'.join(p.get('text', '') for m in context['data'] for p in m.get('content', []) if p.get('type') == 'text')
        assert stats_text and stats_text in parent_text, 'stats not shown verbatim'
        children = api('GET', '/api/session?' + urlencode({'parentID': sid, 'limit': 100}))['data']
        save('children', children)
        assert set(child_ids) == {c['id'] for c in children}
        override_delivered = False
        for child in children:
            assert child['model'] == auth['model'] and child['location']['directory'] == str(work)
            child_context = api('GET', f'/api/session/{child["id"]}/context')
            save(child['id'] + '-context', child_context)
            raw = json.dumps(child_context)
            override_delivered |= 'DOC-OVERRIDE-15' in raw
            assert not any(c.get('name') == 'subagent' for m in child_context['data'] for c in m.get('content', []))
        assert override_delivered, 'project override lost after move'
        statuses = [json.loads(p.read_text()) for p in (run / 'exec').rglob('status.json')]
        external = [s for s in statuses if 'stdout_file' in s]
        assert len(external) == 1 and external[0]['state'] == 'clean', external
        assert external[0]['returncode'] == 0 and not external[0]['timed_out'], external
        moves = [s for s in git(work, 'log', '--format=%s').splitlines() if s.startswith('docs: move completed plan')]
        assert len(moves) == 1
        review = load(root / 'plugins/planning/skills/exec/scripts/exec-review.py', 'review')
        usage = review.stats(sid)
        save('usage', usage)
        assert usage['coverage'] == 'complete' and len(usage['sessions']) == len(children) + 1
        assert api('GET', f'/api/session/{args.parent}')['data']['location'] == auth['parent_location']
        save('results', {'sessionID': sid, 'worktree': str(work), 'children': len(children), 'two_tasks_sequential': True,
            'five_way_overlap': True, 'source_preserved': True, 'project_override_delivered': True,
            'external': external, 'stats_coverage': usage['coverage'], 'sole_plan_move': True,
            'stats_verbatim': True, 'final_critical_overlap': True, 'phase_order': True,
            'review': 'real revdiff, controlled PTY, NO HUMAN', 'chain': 'one session, same absolute/remapped plan identity'})
        print('PASS connected automated chain (human gates remain pending)', flush=True)
    except Exception as exc:
        (run / ('failure-' + str(len(list(run.glob('failure-*')))) + '.txt')).write_text(repr(exc) + '\n')
        if sid:
            save('failure-context', api('GET', f'/api/session/{sid}/context'))
        raise


if __name__ == '__main__':
    main()
