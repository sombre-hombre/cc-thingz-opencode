#!/usr/bin/env python3
"""Real active-service discovery/admission, deliberately absent model: NO model E2E.

Copies only named old-port code definitions READ ONLY, never data/settings/auth.
Runs branch-name regression in two independent disposable Git repositories.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlencode


def main():
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-port-admission.', dir='/tmp/opencode'))
    print('Artifacts:', run, flush=True)
    work = run / 'workspace with spaces'
    work.mkdir()

    def save(name, data):
        (run / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')

    def api(method, path, body=None):
        argv = ['opencode', 'api', method.lower(), path]
        if body is not None:
            argv += ['--data', json.dumps(body)]
        with tempfile.TemporaryFile(mode='w+', dir='/tmp/opencode') as out:
            p = subprocess.run(argv, stdout=out, stderr=subprocess.PIPE, text=True, timeout=300)
            assert p.returncode == 0, p.stderr
            out.seek(0)
            text = out.read()
            return json.loads(text) if text.strip() else None

    manifest = json.loads((root / 'install-manifest.json').read_text())
    for group in ('skills', 'commands', 'agents'):
        for entry in manifest[group]:
            target = work / '.opencode' / entry['target']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(root / entry['source'])
    (work / 'opencode.json').write_text(json.dumps({'$schema': 'https://opencode.ai/config.json', 'snapshots': False}) + '\n')
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    subprocess.run(['git', 'init', '-qb', 'main'], cwd=work, env=env, check=True)
    sid = api('POST', '/api/session', {'title': 'Task15 all entrypoint admission NO model',
        'location': {'directory': str(work)}, 'model': {'providerID': 'missing-port-audit', 'id': 'missing'}})['data']['id']
    query = '?' + urlencode({'location[directory]': str(work)})
    deadline = time.monotonic() + 30
    while True:
        skills = api('GET', '/api/skill' + query)['data']
        if len(skills) >= 17:
            break
        assert time.monotonic() < deadline, 'activation timeout'
        time.sleep(.2)
    commands = api('GET', '/api/command' + query)['data']
    agents = api('GET', '/api/agent' + query)['data']
    save('registry', {'skills': skills, 'commands': commands, 'agents': agents})
    for entry in manifest['skills']:
        found = [s for s in skills if s['id'] == entry['id']]
        assert len(found) == 1 and Path(found[0]['path']).resolve() == root / entry['source'] / 'SKILL.md'
    for group, registry in (('commands', commands), ('agents', agents)):
        for entry in manifest[group]:
            ident = Path(entry['target']).stem
            field = 'name' if group == 'commands' else 'id'
            assert sum(r[field] == ident for r in registry) == 1, (group, ident)
    text, attachments = '', []
    for entry in manifest['skills']:
        mention = '@' + entry['id']
        attachments.append({'id': entry['id'], 'mention': {'start': len(text), 'end': len(text) + len(mention), 'text': mention}})
        text += mention + ' '
    text += 'Admission only, provider deliberately absent.'
    api('POST', f'/api/session/{sid}/prompt', {'text': text, 'skills': attachments})
    api('POST', f'/api/experimental/session/{sid}/wait', {})
    context = api('GET', f'/api/session/{sid}/context')
    save('mentions-context', context)
    user = next(m for m in context['data'] if m.get('type') == 'user')
    assert user['text'] == text
    assert [{'id': s['id'], 'mention': s['mention']} for s in user['skills']] == attachments
    assert all(s['text'].count('<skill_content name=') == 1 for s in user['skills']), 'duplicate activation payload'
    arguments = '"docs/a plan.md"  $(touch MUST_NOT_EXIST) ; literal'
    for entry in manifest['commands']:
        ident = Path(entry['target']).stem
        api('POST', f'/api/session/{sid}/command', {'name': ident, 'text': arguments})
        api('POST', f'/api/experimental/session/{sid}/wait', {})
    context = api('GET', f'/api/session/{sid}/context')
    save('commands-context', context)
    users = [m for m in context['data'] if m.get('type') == 'user']
    assert len(users) == 19
    assert all(arguments in m['text'] for m in users[1:]), 'argument corruption'
    for entry, user_message in zip(manifest['commands'], users[1:]):
        template = (root / entry['source']).read_text().split('---', 2)[2].strip()
        assert user_message['text'].strip() == template.replace('$ARGUMENTS', arguments), entry
    assert not (work / 'MUST_NOT_EXIST').exists()
    assert any(m.get('error', {}).get('type') == 'provider.no-route' for m in context['data'])
    # Activations are explicit and resume:false: the test does not infer dedupe
    # from runtime API (plugin's durable reminder policy has separate tests).
    # Snapshot exactly the public definitions needed for regression comparison.
    installed = Path.home() / '.config/opencode'
    names = ['skills/exec/SKILL.md', 'commands/make.md', 'plugins/plan-annotate-hook.ts']
    helpers = ['create-branch.sh', 'detect-vcs.sh']
    names += ['skills/exec/scripts/' + name for name in helpers]
    before = {}
    for name in names:
        data = (installed / name).read_bytes()
        before[name] = hashlib.sha256(data).hexdigest()
        target = run / 'old-code-snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    results = []
    for label, helper in [('old', run / 'old-code-snapshot/skills/exec/scripts/create-branch.sh'),
                          ('new', root / 'plugins/planning/skills/exec/scripts/create-branch.sh')]:
        repo = run / (label + ' branch repo')
        repo.mkdir()
        subprocess.run(['git', 'init', '-qb', 'main'], cwd=repo, env=env, check=True)
        subprocess.run(['git', '-c', 'user.name=Baseline smoke', '-c', 'user.email=smoke@example.invalid',
                        'commit', '--allow-empty', '-qm', 'baseline'], cwd=repo, env=env, check=True)
        p = subprocess.run(['bash', str(helper), 'docs/plans/two tasks.md'], cwd=repo, env=env, capture_output=True, text=True)
        results.append({'port': label, 'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr,
                        'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo, env=env, text=True).strip()})
    assert results[0]['returncode'] != 0 and 'not a valid branch name' in results[0]['stderr'], results
    assert results[1]['returncode'] == 0 and results[1]['branch'] == 'two-tasks', results
    oldexec = (run / 'old-code-snapshot/skills/exec/SKILL.md').read_text()
    hook = (run / 'old-code-snapshot/plugins/plan-annotate-hook.ts').read_text()
    structural = {'old_exec_requires_todowrite': 'ALWAYS create the task list with the todowrite tool' in oldexec,
                  'old_exec_task_subagent_schema': 'subagent_type: "general"' in oldexec,
                  'old_hook_write_only': 'if (event.tool !== "write") return' in hook,
                  'old_hook_instance_location': 'const directory = ctx.location.directory' in hook}
    assert all(structural.values())
    assert before == {n: hashlib.sha256((installed / n).read_bytes()).hexdigest() for n in names}
    save('results', {'sessionID': sid, 'skills': 17, 'commands': 18, 'agents': 2,
        'mentions': 'real admitted exact IDs/offsets, no model dispatch', 'slash': 'real command expansion, absent provider expected',
        'branch_runtime_comparison': results, 'baseline_structural_only': structural,
        'old_definitions_unchanged_sha256': before, 'no_installed_data_or_auth_snapshot': True})
    print('PASS discovery/admission and observed branch regression; structural baseline is NOT model failure evidence', flush=True)


if __name__ == '__main__':
    main()
