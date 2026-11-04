#!/usr/bin/env python3
"""Opt-in Task16 GLOBAL installation smoke; no project skill/plugin overrides/UI.

Real model exercises wrappers and loaded make/exec resources, not another full
exec run. Full chain and real revdiff baseline are retained from Tasks5-15.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api, wait_idle

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-current-model', action='store_true', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-installed.', dir='/tmp/opencode'))
    print('Artifacts:', run, flush=True)
    work = run / 'workspace with spaces'
    work.mkdir()

    def save(name, data):
        (run / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')

    # No .opencode registry/plugin/instructions overrides: actual global config only.
    (work / 'opencode.json').write_text(json.dumps({'$schema': 'https://opencode.ai/config.json', 'snapshots': False}) + '\n')
    env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
    subprocess.run(['git', 'init', '-qb', 'main'], cwd=work, env=env, check=True, capture_output=True)
    model = {'providerID': 'openai', 'id': 'gpt-6.1-sol', 'variant': 'medium'}
    sid = api('POST', '/api/session', {'title': 'Task16 installed global smoke', 'agent': 'build',
        'location': {'directory': str(work)}, 'model': model,
        'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]})['data']['id']
    save('session', {'sessionID': sid, 'model': model, 'directory': str(work)})
    query = '?' + urlencode({'location[directory]': str(work)})
    manifest = json.loads((root / 'install-manifest.json').read_text())
    deadline = time.monotonic() + 60
    while True:
        skills = api('GET', '/api/skill' + query)['data']
        if all(any(s['id'] == e['id'] for s in skills) for e in manifest['skills']):
            break
        assert time.monotonic() < deadline, 'global skill activation timeout'
        time.sleep(.2)
    commands = api('GET', '/api/command' + query)['data']
    agents = api('GET', '/api/agent' + query)['data']
    plugins = api('GET', '/api/plugin' + query)['data']
    save('registry', {'skills': skills, 'commands': commands, 'agents': agents, 'plugins': plugins})
    for entry in manifest['skills']:
        found = [s for s in skills if s['id'] == entry['id']]
        assert len(found) == 1 and Path(found[0]['path']).resolve() == root / entry['source'] / 'SKILL.md', entry
    for group, registry in [('commands', commands), ('agents', agents)]:
        field = 'name' if group == 'commands' else 'id'
        for e in manifest[group]:
            assert sum(r[field] == Path(e['target']).stem for r in registry) == 1, e
    plugin = [p for p in plugins if p.get('id') == 'cc-thingz.skill-eval']
    assert len(plugin) == 1, plugins
    assert plugin[0]['state']['status'] == 'active', plugin
    assert Path(plugin[0]['source']['path']).resolve() == root / 'integrations/opencode/skill-eval/index.ts', plugin
    assert 'plan-annotate-hook' not in json.dumps(plugins), plugins
    save('plugin-status', plugin)
    api('POST', f'/api/session/{sid}/command', {'name': 'writing-style', 'text':
        'Rewrite this technical comment only: "I hope you are well. arithmetic.py:2 subtracts instead of adding; use a + b." '
        'No edits, children, UI or global configuration reads.'})
    wait_idle(api, save, sid)
    api('POST', f'/api/session/{sid}/prompt', {'text':
        '@make @exec Installation smoke only, not a request to create/execute a plan. '
        'Both skills are attached; do not activate them again. Read the installed make SKILL and '
        'exec active references/prompts/task-loop.md through their canonical bases, then report the '
        'canonical package root, validated settings-reader helper path and sequential/no-nested-fanout contract. '
        'Do not create a plan, dispatch children, change files, ask questions, launch UI, read global config/data '
        'or execute any workflow. Only these source resource reads and realpath shell commands are authorized.',
        'skills': [{'id': 'make', 'mention': {'start': 0, 'end': 5, 'text': '@make'}},
                   {'id': 'exec', 'mention': {'start': 6, 'end': 11, 'text': '@exec'}}]})
    wait_idle(api, save, sid)
    api('POST', f'/api/session/{sid}/command', {'name': 'review-plan', 'text':
        f'Review-only "{work / "missing plan.md"}". Deliberately absent; report missing, never approved. '
        'No creation/edits/commits/children/questions/UI/global config/data reads. Reuse attached make.'})
    wait_idle(api, save, sid)
    context = api('GET', f'/api/session/{sid}/context')
    save('context', context)
    assert not [m for m in context['data'] if m.get('type') == 'idle' and m.get('error')]
    calls = [c for m in context['data'] for c in m.get('content', []) if c.get('type') == 'tool']
    assert not [c for c in calls if c['name'] in ('patch', 'write', 'subagent', 'question')]
    loads = [c['state']['input']['id'] for c in calls if c['name'] == 'skill' and c['state']['status'] == 'completed']
    assert loads == ['writing-style'], loads
    assert any('task-loop.md' in json.dumps(c['state'].get('input', {})) for c in calls if c['name'] == 'read')
    users = [m for m in context['data'] if m.get('type') == 'user']
    assert [s['id'] for s in users[1]['skills']] == ['make', 'exec']
    assert 'V2 Workflow Entry Point' in users[1]['skills'][1]['text'] or 'task-loop.md' in users[1]['skills'][1]['text']
    assert not (work / 'missing plan.md').exists()
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'opencode'
    # Installed launcher reaches explicit skipped status without terminal/UI. Not human acceptance.
    plan = run / 'plan with spaces.md'
    plan.write_text('# Installed launcher probe\n')
    output, status = run / 'annotations.md', run / 'review-status.json'
    p = subprocess.run(['bash', str((config / 'skills/make').resolve().parents[1] / 'scripts/launch-plan-review.sh'),
        str(plan), '--output', str(output), '--status', str(status)], cwd=work,
        env=dict(os.environ, PLANNING_DISABLE_REVDIFF='1'), text=True, capture_output=True, timeout=30)
    assert p.returncode == 0 and json.loads(status.read_text())['state'] == 'skipped', p.stderr
    save('results', {'sessionID': sid, 'model': model, 'registry': {'skills': 17, 'commands': 18, 'agents': 2, 'plugin': 1},
        'source': str(root), 'activations': loads, 'make_exec': 'actual composer attachments/resource reads; no execution',
        'review_plan': 'actual wrapper reuses make; missing file not created/approved',
        'launcher': 'installed path skipped by explicit disable; real revdiff baseline Tasks5/6/15, no new UI',
        'parent': 'not read or mutated', 'global_registry': 'no project skills/plugins overrides'})
    print('PASS installed registry/wrappers/model/resources/launcher', flush=True)


if __name__ == '__main__':
    main()
