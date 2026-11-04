#!/usr/bin/env python3
"""Opt-in real-model regression: slash reuses attached/previously loaded skill."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api, wait_idle

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-current-model', required=True, action='store_true')
    parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-port-activation.', dir='/tmp/opencode'))
    print('Artifacts:', run, flush=True)

    def save(name, data):
        (run / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')

    work = run / 'workspace'
    for ident, source in [('make', 'planning'), ('writing-style', 'review')]:
        target = work / '.opencode/skills' / ident
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(root / 'plugins' / source / 'skills' / ident)
    (work / '.opencode/commands').mkdir()
    for name in ('writing-style', 'review-plan'):
        (work / '.opencode/commands' / (name + '.md')).symlink_to(root / 'commands' / (name + '.md'))
    (work / 'opencode.json').write_text(json.dumps({'$schema': 'https://opencode.ai/config.json', 'snapshots': False}) + '\n')
    subprocess.run(['git', 'init', '-qb', 'main'], cwd=work, check=True, capture_output=True)
    sid = api('POST', '/api/session', {'title': 'Task15 activation reuse regression', 'agent': 'build',
        'location': {'directory': str(work)}, 'model': {'providerID': 'openai', 'id': 'gpt-6.1-sol', 'variant': 'medium'},
        'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]})['data']['id']
    api('POST', f'/api/session/{sid}/command', {'name': 'writing-style', 'text':
        'Rewrite technical comment only: "I hope you are well. cache.py:3 returns an expired value at now=10. Add an equality test." No edits, no global config/override reads.'})
    wait_idle(api, save, sid)
    api('POST', f'/api/session/{sid}/command', {'name': 'writing-style', 'text':
        'Rewrite this second technical comment: "Just wanted to say that zero must raise ValueError." No edits, no global config/override reads.'})
    wait_idle(api, save, sid)
    # Actual composer attachment supplies make before invoking review-plan.
    api('POST', f'/api/session/{sid}/prompt', {'text': '@make Keep this skill available for my next review-only command. '
        'No planning, tools, questions, implementation or config reads now; reply READY.',
        'skills': [{'id': 'make', 'mention': {'start': 0, 'end': 5, 'text': '@make'}}]})
    wait_idle(api, save, sid)
    api('POST', f'/api/session/{sid}/command', {'name': 'review-plan', 'text':
        f'Review-only {work / "missing plan.md"}. Missing file is deliberate: report missing/error, not approval; '
        'do not create a plan, launch UI, implement, commit, ask questions, or read global config/settings/overrides.'})
    wait_idle(api, save, sid)
    context = api('GET', f'/api/session/{sid}/context')
    save('context', context)
    assert not [m for m in context['data'] if m.get('type') == 'idle' and m.get('error')]
    calls = [c for m in context['data'] for c in m.get('content', []) if c.get('type') == 'tool']
    loads = [c['state']['input']['id'] for c in calls if c['name'] == 'skill' and c['state']['status'] == 'completed']
    assert loads == ['writing-style'], loads
    user = next(m for m in context['data'] if m.get('skills'))
    assert user['skills'][0]['id'] == 'make'
    assert not (work / 'missing plan.md').exists()
    assert not [c for c in calls if c['name'] in ('patch', 'write', 'subagent', 'question')]
    save('results', {'sessionID': sid, 'tool_activations': loads, 'writing_style_commands': 2,
                    'make': 'composer attachment reused by review-plan without skill tool reload',
                    'missing_plan': 'not created/not approved', 'human_UI': 'not run'})
    print('PASS real current-session reuse (one initial tool activation, no reload)', flush=True)


if __name__ == '__main__':
    main()
