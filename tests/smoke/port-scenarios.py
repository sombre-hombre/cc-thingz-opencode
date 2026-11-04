#!/usr/bin/env python3
"""Additional Task15 end-user model scenarios. GitLab is loopback-only fixture.

No remote writes, no credentials/config copying; exact current model requires
explicit authorization. Actual outputs remain under /tmp/opencode.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import api, wait_idle

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-current-model', required=True, action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-port-scenarios.', dir='/tmp/opencode'))
    print('Artifacts:', run, flush=True)
    fixtures = module(root / 'tests/test-release-tools.py', 'release_tests').ReleaseTests()
    fixtures.setUp()
    context_fixture = module(root / 'tests/test-gitlab-review.py', 'mr_tests').GitLabTests()
    context_fixture.setUp()
    wait = wait_idle
    model = {'providerID': 'openai', 'id': 'gpt-6.1-sol', 'variant': 'medium'}

    def save(name, value):
        (run / (name + '.json')).write_text(json.dumps(value, indent=2) + '\n')

    try:
        work = run / 'workspace with spaces'
        shutil.copytree(fixtures.repo, work)
        fixtures.repo = work
        for ident, source in [('release', 'release-tools'), ('last-tag', 'release-tools'),
                              ('pr', 'review'), ('writing-style', 'review')]:
            target = work / '.opencode/skills' / ident
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(root / 'plugins' / source / 'skills' / ident)
            command = work / '.opencode/commands' / (ident + '.md')
            command.parent.mkdir(parents=True, exist_ok=True)
            command.symlink_to(root / 'commands' / (ident + '.md'))
        (work / 'opencode.json').write_text(json.dumps({'$schema': 'https://opencode.ai/config.json', 'snapshots': False}) + '\n')
        (work / 'AGENTS.md').write_text('Isolated smoke. No push, fetch, publication, edits, global config or credentials access. No subagents. Only explicitly supplied fixture commands may access HTTP.\n')
        (work / 'changelog.md').write_text('# Changes\n\n## Unreleased\n')
        fixtures.git('add', '.')
        fixtures.git('commit', '-qm', 'fixture config')
        fixtures.git('tag', 'v1.2.3')
        fixtures.commit('feat: add auth')
        fixtures.commit('fix: local-only correction')
        fixtures.pages = [[fixtures.mr(7, 'feat: add auth', '2999-01-01T00:00:00Z')],
                          [fixtures.mr(101, 'fix: fix timeout', '2999-01-01T00:00:00Z')]]
        prefetched = context_fixture.run_context()
        assert prefetched.returncode == 0, prefetched.stderr
        (run / 'mr-context.json').write_text(prefetched.stdout)
        save('before', {'head': fixtures.git('rev-parse', 'HEAD'), 'status': fixtures.git('status', '--porcelain'),
                        'tags': fixtures.git('tag'), 'changelog': (work / 'changelog.md').read_text()})
        helper = root / 'plugins/release-tools/skills/release/scripts/release.py'
        prefix = shlex.join(['env', *[k + '=' + v for k, v in fixtures.env.items()], 'python3', str(helper)])
        scenarios = {
            'release': 'Minor release PREVIEW ONLY, offline/local unrefreshed tags explicitly agreed; no fetch/tag/push/publication/changelog edits. '
                'Use exact fixture-only helper command prefix below for detect/version/notes/preview: ' + prefix + '. '
                f'Run with workdir {work}; save preview artifacts ONLY under {run / "release-preview"}. '
                'Show proposed v1.3.0 title and categorized notes including MR !101 and local-only correction; disclose unrefreshed tags. Stop before confirmation. '
                'Do not invoke glab directly or read global config; the prefix isolates HOME/XDG/glab to fixture-only token and loopback routing. '
                'No questions: all decisions supplied.',
            'last-tag': 'Explicit offline/local unrefreshed tags mode; no fetch/network. Show since v1.2.3 commits table with single author and both subjects '
                'add auth, local-only correction. Then show git show --stat details for the latest displayed commit; this drilldown is explicitly selected. '
                'Use actual bundled helper and Git; no edits or questions.',
            'pr': f'Quick review MR https://gitlab.fixture.test/team/platform/service/-/merge_requests/42. '
                f'Use complete pre-fetched real-helper context at {run / "mr-context.json"}, supplied as immutable fixture data for this model scenario; '
                'do not refetch or contact remote. Quick selected, Done after assessment; no draft/comments/approval/merge/worktree/children. '
                'Read second-page discussion, distinguish IID42 from global9001, capped diff/CI-running/unavailable approval data. '
                'Do not claim clean/full coverage or merge-ready. Summarize scope and one actionable concern, report known gaps. No questions.',
            'writing-style': 'Rewrite this technical MR comment without filler, retaining exact facts and avoiding invented tests: '
                '"I hope this message finds you well. I wanted to take a moment to mention that cache.py line 3 uses > rather than >=. '
                'At now=10 and expires_at=10 the expired value is returned. The two existing tests pass; they do not cover equality. '
                'It might be worthwhile to consider adding a boundary test." Output only the rewritten comment, no file edits. '
                'Use applicable project guidance; do not read any global configs, credentials or private overrides.',
        }
        sessions = {}
        for ident, text in scenarios.items():
            sid = api('POST', '/api/session', {'title': 'Task15 ' + ident, 'agent': 'build', 'model': model,
                'location': {'directory': str(work)}, 'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]})['data']['id']
            sessions[ident] = sid
            api('POST', f'/api/session/{sid}/command', {'name': ident, 'text': text})
        save('sessions', sessions)
        for ident, sid in sessions.items():
            wait(api, save, sid)
            context = api('GET', f'/api/session/{sid}/context')
            save(ident + '-context', context)
            assert not [m for m in context['data'] if m.get('type') == 'idle' and m.get('error')]
            calls = [c for m in context['data'] for c in m.get('content', []) if c.get('type') == 'tool']
            assert any(c['name'] == 'skill' and c['state'].get('input') == {'id': ident} and c['state']['status'] == 'completed' for c in calls)
            forbidden = ('subagent', 'question') if ident == 'release' else ('subagent', 'question', 'patch', 'write')
            assert not [c for c in calls if c['name'] in forbidden], (ident, 'unexpected mutation or question')
            text = '\n'.join(c.get('text', '') for m in context['data'] if m.get('type') == 'assistant' for c in m.get('content', []) if c.get('type') == 'text')
            (run / (ident + '-answer.md')).write_text(text)
            if ident == 'release':
                assert all(s in text for s in ('v1.3.0', '!101', 'local-only'))
            elif ident == 'last-tag':
                assert all(s in text for s in ('v1.2.3', '|', 'local-only', 'add auth'))
            elif ident == 'pr':
                assert '42' in text and ('CI' in text or 'ci' in text)
            else:
                assert '10' in text and '>=' in text and 'equality' in text.lower()
                assert 'finds you well' not in text.lower()
        before = json.loads((run / 'before.json').read_text())
        assert before == {'head': fixtures.git('rev-parse', 'HEAD'), 'status': fixtures.git('status', '--porcelain'),
                          'tags': fixtures.git('tag'), 'changelog': (work / 'changelog.md').read_text()}
        assert all(c[0] == 'GET' for c in fixtures.calls + context_fixture.calls)
        save('results', {'sessions': sessions, 'model': model, 'source_unchanged': True,
             'release_http': fixtures.calls, 'pr_prefetch_http': context_fixture.calls,
             'remote_writes': 0, 'scope': 'release live model + real loopback helper; PR model uses pre-fetched fixture; local last-tag/style'})
        print('PASS additional model scenarios; no remote GitLab acceptance claimed', flush=True)
    except Exception as exc:
        (run / 'failure.txt').write_text(repr(exc) + '\n')
        raise
    finally:
        fixtures.doCleanups()
        context_fixture.doCleanups()


if __name__ == '__main__':
    main()
