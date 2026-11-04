"""Small shared native CLI transport; no model admission retries."""
import json
import re
import subprocess
import tempfile
import time


def api(method, path, body=None, timeout=1800, executable='opencode'):
    argv = [executable, 'api', method.lower(), path]
    if body is not None:
        argv += ['--data', json.dumps(body)]
    try:
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8', dir='/tmp/opencode') as output:
            proc = subprocess.run(argv, stdout=output, stderr=subprocess.PIPE, text=True, timeout=timeout)
            if proc.returncode:
                raise RuntimeError(f'API {path} exit {proc.returncode}: {proc.stderr}')
            output.seek(0)
            text = output.read()
            return json.loads(text) if text.strip() else None
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'API {path} TimeoutError: {exc}') from exc


def wait_idle(api, save, sid, deadline_seconds=1500):
    """Reconnect only blocking wait after timeout; never redispatch a model."""
    deadline = time.monotonic() + deadline_seconds
    attempt = 0
    while True:
        try:
            api('POST', f'/api/experimental/session/{sid}/wait', {})
            return
        except RuntimeError as exc:
            if 'TimeoutError' not in str(exc) or time.monotonic() >= deadline:
                raise
            attempt += 1
            save(f'wait-transport-timeout-{int(time.time())}-{attempt}',
                 {'error': str(exc), 'sessionID': sid,
                  'action': 'reconnect same blocking wait, no model redispatch'})


def assert_findings_delivered(call, fixer_prompt, received_reads):
    output = '\n'.join(p['text'] for p in call['state'].get('content', []) if p.get('type') == 'text')
    actual = re.sub(r'^<subagent[^>]*>\n|\n</subagent>$', '', output).strip()
    assert actual, 'completed reviewer has no actual final response'
    assert call['state'].get('metadata', {}).get('truncated') is not True, 'truncated findings'
    assert actual in fixer_prompt or actual in received_reads, 'fixer did not receive full unfiltered findings'
    return output
