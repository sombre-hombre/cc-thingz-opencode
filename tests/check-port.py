#!/usr/bin/env python3
"""Validate the deliverable graph, not prompt wording or model compliance.

No installed config reads, network, subprocesses or installer side effects.
HTML comments are archived prose; executable source is tested by runtime suites.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

EXPECTED = set('brainstorm pr git-review writing-style exec make release last-tag ask-codex dialectic root-cause-investigator learn clarify wrong md-copy txt-copy backlog'.split())
GROUPS = ('skills', 'commands', 'agents', 'plugins')
REQUIRED_SUITES = '''brainstorm-resolve-rules exec-active-smoke exec-review exec-task-loop
exec-vcs-detect exec-vcs-dispatch gitlab-review install planning-disable-review
planning-external-review planning-resolve-rules planning-settings planning-workflow
port-audit release-tools revdiff-git-review revdiff-plan skill-eval thinking-tools
v2-packaging workflow worktree-isolation'''.split()


def active(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def validate(root):
    root = Path(root).resolve()
    errors, targets, ids, documents = [], set(), {}, set()

    def require(ok, message):
        if not ok:
            errors.append(message)

    def local(value, label):
        p = Path(value)
        safe = not p.is_absolute() and '..' not in p.parts and value not in ('', '.')
        require(safe, f'{label}: unsafe path {value!r}')
        if safe:
            require((root / p).resolve().is_relative_to(root), f'{label}: symlink escapes package {value!r}')
        return root / p if safe else root / '__invalid_path__'

    try:
        lock = json.loads((root / 'upstream.lock').read_text())
        require(lock['commit'] == 'f84b93ca0f04a1406bdbb834d8f1ed1946996d1e'
                and lock['license'] == 'MIT' and lock['url'] == 'https://github.com/umputun/cc-thingz.git',
                'upstream provenance changed without audit update')
        require(hashlib.sha256((root / 'LICENSE').read_bytes()).hexdigest() ==
                '155d97114b2d9b7f66181d0ba258aca57f97b8b957dd1662745bf57218c41ef3', 'upstream MIT license changed')
        for suite in REQUIRED_SUITES:
            require((root / 'tests' / f'test-{suite}.sh').is_file(), f'missing mandatory suite {suite}')
        manifest = json.loads((root / 'install-manifest.json').read_text())
        require(manifest['version'] == 1 and manifest['configRoot'] == 'opencode', 'unsupported manifest contract')
        for group in GROUPS:
            entries = manifest[group]
            require(isinstance(entries, list), f'{group}: expected list')
            ids[group] = set()
            for entry in entries:
                source = local(entry['source'], group + ' source')
                target = entry['target']
                local(target, group + ' target')
                require(target not in targets, f'duplicate target {target}')
                require(not any(target.startswith(t + '/') or t.startswith(target + '/') for t in targets),
                        f'overlapping target {target}')
                targets.add(target)
                require(Path(target).parts[0] == group, f'{target}: wrong registry')
                require(source.exists(), f'missing source {entry["source"]}')
                require('hooks' not in source.parts and '.claude-plugin' not in source.parts, f'Claude autoload entry {source}')
                ident = entry.get('id', Path(target).stem)
                require(ident not in ids[group], f'{group}: duplicate ID {ident}')
                ids[group].add(ident)
                if group == 'skills':
                    require(target == f'skills/{ident}', f'path-derived ID mismatch {target}')
                    text = (source / 'SKILL.md').read_text()
                    name = re.search(r'^name:\s*[\"\']?([^\n\"\']+)', text, re.M)
                    require(name is not None and name[1].strip() == ident, f'skill name mismatch {source}')
                    require(re.search(r'^description:\s*\S', text, re.M), f'missing description {source}')
                    documents.update(source.rglob('*.md'))
                    documents.update(source.rglob('*.txt'))
                elif group in ('commands', 'agents'):
                    documents.add(source)
                    text = source.read_text()
                    if group == 'commands':
                        calls = set(re.findall(r'\bid[\"\']?\s*:\s*[\"\']([^\"\']+)', text))
                        expected = 'make' if ident == 'review-plan' else ident
                        require(calls == {expected}, f'{target}: wrong skill activation {calls}')
                        require(text.count('$ARGUMENTS') == 1 and '!`' not in text and '$1' not in text,
                                f'{target}: unsafe/lost argument transport')
                        require(re.search(r'^subagent:\s*false$', text, re.M), f'{target}: fresh context wrapper')
                    else:
                        require(re.search(r'^mode:\s*subagent$', text, re.M), f'{target}: invalid mode')
                        require('\npermissions:' in text and not re.search(r'^model:', text, re.M),
                                f'{target}: missing permissions or unrequested model')
                else:
                    require(source.is_relative_to(root / 'integrations/opencode'), f'non-V2 plugin {source}')
                    package = json.loads((source / 'package.json').read_text())
                    require((source / package['exports']['.']).is_file(), f'missing plugin export {source}')
                    require(package['dependencies']['@opencode/plugin'] == '2.1.1', 'unverified SDK version')
        require(ids['skills'] == EXPECTED, f'skill coverage mismatch {ids["skills"] ^ EXPECTED}')
        require(ids['commands'] == EXPECTED | {'review-plan'}, 'command coverage mismatch')
        require(ids['agents'] == {'plan-review', 'external-plan-review'}, 'planning agent coverage mismatch')
        require(ids['plugins'] == {'cc-thingz.skill-eval'}, 'hook function coverage mismatch')
        release = next(e for e in manifest['skills'] if e['id'] == 'release')
        require(release.get('upstreamID') == 'new', 'lost release provenance')
        discovered = {str(p.parent.relative_to(root)) for p in root.glob('plugins/*/skills/*/SKILL.md')}
        require(discovered == {e['source'] for e in manifest['skills']}, 'unmapped/duplicate source skill')
        require(set(manifest['excluded']) >= {'plugins/*/hooks/*', 'plugins/*/.claude-plugin/*'}, 'Claude metadata not excluded')
        documents.update(root.glob('plugins/*/references/*.md'))
        # Concrete resource tokens only. Dynamic user/project examples and template
        # slots are not filesystem paths; do not invent their resolution here.
        for doc in sorted(documents):
            text = active(doc.read_text())
            rel = str(doc.relative_to(root))
            require(not re.search(r'\$\{?CLAUDE_PLUGIN|\$\{user_config\.|(?<!\w)\.claude/|`/\w+:[\w-]+', text), f'{rel}: active legacy dependency')
            if '/commands/' not in '/' + rel and not rel.startswith('commands/'):
                require('$ARGUMENTS' not in text, f'{rel}: unexpanded command token')
            require(not re.search(r'\b(?:subagent_type|todowrite)\s*[:(]|\bTask\s*\(', text), f'{rel}: obsolete tool schema')
            require(not re.search(r'^(?:allowed-tools|argument-hint):', text, re.M), f'{rel}: Claude frontmatter')
            bases = [doc.parent]
            if '/references/' in rel:
                resource_root = Path(str(doc).split('/references/')[0])
                bases.extend([resource_root, resource_root / 'references'])
                if resource_root == root / 'plugins/planning':
                    bases.extend([resource_root / 'skills/exec', resource_root / 'skills/exec/references'])
            if '/skills/' in rel:
                skillbase = Path(str(doc).split('/skills/')[0]) / 'skills' / rel.split('/skills/')[1].split('/')[0]
                bases.extend([skillbase, skillbase / 'references', skillbase.parent.parent])
                if skillbase == root / 'plugins/planning/skills/make':
                    bases.append(root)  # Explicit package-root settings dependency.
            for token in re.findall(r'`((?:\.\./)*(?:references/|scripts/|prompts/|agents/)[\w./-]+\.(?:md|txt|sh|py))`', text):
                require(any((b / token).is_file() for b in bases), f'{rel}: broken resource {token}')
            # Explicit cross-group relative dependencies, e.g. ask-codex → exec
            # and last-tag → release, retain their canonical skill-relative scope.
            for token in re.findall(r'`((?:\.\./)+[\w./-]+\.(?:md|txt|sh|py))`', text):
                require(any((b / token).is_file() for b in bases), f'{rel}: broken relative resource {token}')
            # Commands contain placeholders before /scripts, so inline-code-only
            # parsing above cannot discover their helper dependency.
            if '/skills/exec/' in rel:
                for token in set(re.findall(r'\bscripts/[\w-]+\.(?:py|sh)', text)):
                    scoped_bases = bases + ([root] if token == 'scripts/read-planning-settings.py' else [])
                    require(any((b / token).is_file() for b in scoped_bases), f'{rel}: broken resource {token}')
            for link in re.findall(r'\]\(([^\s)]+)\)', text):
                if ':' in link or link.startswith('#') or link == 'url':
                    continue
                require((doc.parent / link.split('#')[0]).exists(), f'{rel}: broken Markdown link {link}')
        # Cross-group dependencies cannot be inferred from a single skill copy.
        for resource in ('scripts/read-planning-settings.py', 'plugins/workflow/scripts/clipboard.py',
                         'plugins/planning/scripts/launch-plan-review.sh',
                         'plugins/review/skills/pr/scripts/gitlab-context.py'):
            require((root / resource).is_file(), f'missing shared resource {resource}')
        return {'skills': len(ids['skills']), 'commands': len(ids['commands']), 'agents': len(ids['agents']),
                'plugins': len(ids['plugins']), 'active_documents': len(documents),
            'archive_policy': 'HTML comments and excluded Claude hooks are not active entrypoints', 'errors': errors}
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        errors.append(f'invalid package: {exc}')
        return {'errors': errors}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    result = validate(parser.parse_args().root)
    print(json.dumps(result, indent=2))
    sys.exit(bool(result['errors']))
