#!/usr/bin/env python3
"""Real Git + revdiff + worker, invisible PTY; no graphical UI or model run."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    script = root / 'plugins/review/skills/git-review/scripts/git-review.py'
    spec = importlib.util.spec_from_file_location('git_review', script)
    review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(review)
    run = Path(tempfile.mkdtemp(prefix='cc-thingz-git-review-pty.', dir='/tmp/opencode'))
    print(f'Artifacts: {run}', flush=True)
    repo = run / 'repository with spaces'
    repo.mkdir()
    os.chdir(repo)
    def git(*args):
        subprocess.run(['git', *args], check=True, capture_output=True)
    git('init', '-q', '-b', 'main')
    source = repo / "code ' sample.py"
    source.write_text('def value():\n    return 1\n')
    git('add', '.')
    git('-c', 'user.email=test@local', '-c', 'user.name=test', 'commit', '-qm', 'initial')
    source.write_text('def value():\n    return 2  # Last line marker\n')
    bin_dir = run / 'bin'
    bin_dir.mkdir()
    fixture = bin_dir / 'kitty'
    fixture.write_text('#!' + sys.executable + '\nimport runpy, sys\nsys.argv.insert(1, "--pty-terminal")\nrunpy.run_path('
                       + repr(str(root / 'tests/smoke/no-tmux-plan-review.py')) + ', run_name="__main__")\n')
    fixture.chmod(0o755)
    assert shutil.which('revdiff'), 'missing revdiff'
    snapshot = review.build_snapshot(review.select_diff())
    row = next(i for i, m in enumerate(snapshot['line_map'], 1)
               if m and m.get('kind') == 'added' and m.get('new') == 2)
    results = []
    for mode in ('annotation', 'empty', 'discard', 'close'):
        output, status = run / f'{mode}.md', run / f'{mode}.json'
        screen = run / f'{mode}.screen'
        env = dict(os.environ, PATH=f'{bin_dir}:' + os.environ['PATH'], PROBE_ROW=str(row),
                   PROBE=mode, SCREEN=str(screen), TERM='xterm-256color')
        env.pop('PLANNING_DISABLE_REVDIFF', None)
        process = subprocess.run([sys.executable, str(script), '--terminal', 'kitty-window',
                                  '--wayland-display', 'fixture-no-display', '--xdg-runtime-dir', str(run),
                                  '--output', str(output), '--status', str(status), '--timeout', '20'],
                                 env=env, capture_output=True, timeout=35)
        data = json.loads(status.read_text())
        expected = {'annotation': 'annotations', 'empty': 'needs-confirmation',
                    'discard': 'needs-confirmation', 'close': 'cancelled'}[mode]
        assert data['state'] == expected, (mode, data, process.stderr)
        assert (process.returncode == 0) == (mode != 'close'), (mode, process.returncode)
        annotations = output.read_text()
        assert bool(annotations) == (mode == 'annotation')
        if mode == 'annotation':
            actual_row = int(re.search(r'## review.diff:(\d+)', annotations)[1])
            assert actual_row == row, (actual_row, row, annotations)
            assert data['line_map'][actual_row - 1] == {'path': source.name, 'kind': 'added', 'old': None, 'new': 2}
            subprocess.run([sys.executable, str(script), '--check-status', str(status)], check=True)
        assert b'Last line marker' in screen.read_bytes()
        results.append({'probe': mode, 'state': data['state'], 'exit': process.returncode,
                        'revdiff_exit': data['launcher']['revdiff_exit']})
        (run / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
