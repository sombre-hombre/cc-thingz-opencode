#!/usr/bin/env python3
"""Plan admission and bounded sequential dispatch state; never launches agents.

CLI: task-loop.py select DIRECTORY [PLAN]
     task-loop.py next PLAN PROGRESS RETRIES
     task-loop.py delegate-move PLAN PROGRESS TASK_ID
     task-loop.py check-move PLAN PROGRESS
     task-loop.py complete-move PLAN PROGRESS DESTINATION
     task-loop.py render TEMPLATE CONTEXT_JSON
The parent awaits the returned subagent call, then invokes next again.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def tasks(path):
    with Path(path).open(newline='') as stream:
        text = stream.read()
    result, current, fence = [], None, None
    comment = False
    code_end = 0
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.splitlines()[0]
        start = offset
        offset += len(raw_line)
        # Mask comments without shifting checkbox offsets. Fenced examples are
        # literal: their comment delimiters must not affect following tasks.
        if not fence:
            visible, cursor = [], 0
            while cursor < len(line):
                if start + cursor < code_end:
                    end = min(len(line), code_end - start)
                    visible.append(line[cursor:end])
                    cursor = end
                    continue
                if comment:
                    found = line.find('-->', cursor)
                    end = len(line) if found < 0 else found + 3
                    visible.append(' ' * (end - cursor))
                    comment = found < 0
                    cursor = end
                elif line[cursor] == '\\':
                    # Markdown escapes punctuation in pairs: an odd backslash
                    # makes the following < or backtick literal, even outside code.
                    escaped = cursor + 1 < len(line) and line[cursor + 1] in '<`\\'
                    end = cursor + (2 if escaped else 1)
                    visible.append(line[cursor:end])
                    cursor = end
                elif line.startswith('<!--', cursor):
                    visible.append(' ' * 4)
                    comment = True
                    cursor += 4
                elif not ''.join(visible).strip() and re.match(r'~{3,}', line[cursor:]):
                    # Tilde fence info is literal and may contain backticks.
                    visible.append(line[cursor:])
                    break
                elif line[cursor] == '`':
                    run = re.match(r'`+', line[cursor:])[0]
                    # A fence opener is not an inline code span. Otherwise only
                    # an exact-length closing run shields HTML delimiters. The
                    # supported make-plan subset has single-line inline code;
                    # reject ambiguous/multiline spans, never scan later blocks.
                    is_fence = (not ''.join(visible).strip() and len(run) >= 3
                                and '`' not in line[cursor + len(run):])
                    closing = None if is_fence else re.search(
                        r'(?<!`)`{' + str(len(run)) + r'}(?!`)', line[cursor + len(run):])
                    if closing:
                        code_end = start + cursor + len(run) + closing.end()
                    elif not is_fence:
                        raise ValueError('unsupported inline code: close matching backticks on the same line')
                    visible.append(run)
                    cursor += len(run)
                    if is_fence:
                        visible.append(line[cursor:])
                        break
                else:
                    visible.append(line[cursor])
                    cursor += 1
            line = ''.join(visible)
        # Fences allow only 0..3 ASCII spaces, for openers and closers alike.
        # Indented-code parsing is outside the supported plan subset: reject
        # ambiguous openers rather than silently hiding real pending headings.
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if not fence and not marker and re.match(r"^[ \t]*(`{3,}|~{3,})", line):
            raise ValueError('unsupported fence indentation: use 0..3 spaces, no tabs')
        if marker:
            stripped = line[marker.start(1):]
            char = marker[1][0]
            if fence is None:
                # Backtick fence info cannot contain backticks: a same-line
                # matching run is inline code, not a block hiding later tasks.
                if char == '`' and '`' in stripped[len(marker[1]):]:
                    continue
                fence = (char, len(marker[1]))
            elif (char == fence[0] and len(marker[1]) >= fence[1]
                  and re.fullmatch(r'[ \t]*', line[marker.end(1):])):
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^### (Task|Iteration) ([1-9][0-9]*):\s*(\S.*)$", line)
        if line.startswith("### Task") or line.startswith("### Iteration"):
            if not heading:
                raise ValueError("malformed task heading: " + line)
        if heading:
            current = {"id": heading[1] + " " + heading[2], "title": heading[3], "checks": [], "check_texts": [], "check_positions": []}
            result.append(current)
        elif re.match(r"^#{1,3} ", line):
            current = None
        elif current and re.match(r"^[\s>]*(?:[-*+]|[0-9]+[.)])\s*\[", line):
            # One match supplies status, text/hash and exact source coordinates.
            # Detect a broader candidate first so unsupported list syntax cannot
            # silently disappear from completion admission (e.g. quoted lists).
            check = re.fullmatch(
                r"[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+\[([ xX])\][ \t]+(\S.*)", line)
            if not check:
                raise ValueError("malformed checkbox: " + line)
            current["checks"].append(check[1].lower() == "x")
            current["check_texts"].append(check[2])
            current["check_positions"].append(start + check.start(1))
    if fence:
        raise ValueError("unclosed code fence")
    if comment:
        raise ValueError("unclosed HTML comment")
    if not result or any(not t["checks"] for t in result):
        raise ValueError("plan needs task sections with checkboxes")
    if len({t["id"] for t in result}) != len(result):
        raise ValueError("duplicate task identifier")
    return result


def select(directory, plan=None):
    directory = Path(directory).resolve(strict=True)
    if plan:
        path = Path(plan)
        path = (directory / path).resolve(strict=True) if not path.is_absolute() else path.resolve(strict=True)
    else:
        choices = sorted(p.resolve() for p in directory.glob("*.md") if p.is_file())
        if len(choices) != 1:
            raise ValueError("missing or ambiguous plan: " + json.dumps([str(p) for p in choices]))
        path = choices[0]
    tasks(path)
    return str(path)


def dispatch_state(plan, progress, parsed):
    plan = str(Path(plan).resolve())
    # Durable attempts are append-only in the same progress file, not in a
    # separate in-memory todo list. The parent must serialize calls to next.
    prefix = "[dispatch] "
    attempts = [json.loads(line[len(prefix):]) for line in progress.read_text().splitlines()
                if line.startswith(prefix)]
    task_ids = {t['id'] for t in parsed}
    if any(not isinstance(a, dict) or
           not {'plan', 'task', 'attempt', 'structure'} <= a.keys() or
           not isinstance(a['plan'], str) or not isinstance(a['structure'], str) or
           not isinstance(a['task'], str) or a['task'] not in task_ids or
           type(a['attempt']) is not int or a['attempt'] < 1 for a in attempts):
        raise ValueError('malformed dispatch record')
    if any(a["plan"] != plan for a in attempts):
        raise ValueError("progress belongs to another plan")
    structure = hashlib.sha256(json.dumps([(t["id"], t["title"], t["check_texts"]) for t in parsed]).encode()).hexdigest()
    if any(a["structure"] != structure for a in attempts):
        raise ValueError("task structure changed during execution")
    return attempts, structure


def next_task(plan, progress, retries):
    if retries < 0:
        raise ValueError("retries must be nonnegative")
    plan = str(Path(plan).resolve(strict=True))
    progress = Path(progress).resolve(strict=True)
    parsed = tasks(plan)
    attempts, structure = dispatch_state(plan, progress, parsed)
    delegated = delegation(plan, progress, parsed)
    pending = next((t for t in parsed if not all(done or (t['id'], i) == delegated
                    for i, done in enumerate(t['checks']))), None)
    if pending is None:
        return {"state": "tasks-complete", "total": len(parsed), "completion_move_pending": delegated is not None}
    count = sum(a["task"] == pending["id"] for a in attempts)
    if count >= 1 + retries:
        return {"state": "failed", "task": pending["id"], "reason": "retries exhausted"}
    if len(attempts) >= 50:
        return {"state": "failed", "task": pending["id"], "reason": "50 dispatch limit"}
    record = {"plan": plan, "task": pending["id"], "attempt": count + 1, "structure": structure}
    append(progress, '[dispatch] ', record)
    return {"state": "dispatch", **record, "title": pending["title"]}


def move_record(plan, parsed):
    task = parsed[-1]
    index = len(task['checks']) - 1
    text = task['check_texts'][index]
    match = re.fullmatch(r"move this plan to `([^`\n]+/)`\.?", text, re.I)
    if not match:
        raise ValueError('last checkbox is not a move-only plan action')
    # move-plan.sh supports only sibling completed/. Resolve the requested path
    # in the execution directory, just like other project-relative plan paths.
    if Path(match[1]).resolve() != Path(plan).resolve().parent / 'completed':
        raise ValueError('unsupported completion move destination: expected sibling completed/')
    return {'plan': str(Path(plan).resolve()), 'task': task['id'], 'index': index,
            'text': text, 'structure': [(t['id'], t['title'], t['check_texts']) for t in parsed]}


def delegation(plan, progress, parsed):
    prefix = '[completion-move-delegated] '
    records = [json.loads(line[len(prefix):]) for line in Path(progress).read_text().splitlines()
               if line.startswith(prefix)]
    if not records:
        return None
    expected = json.loads(json.dumps(move_record(plan, parsed)))
    if any(record != expected for record in records):
        raise ValueError('stale or foreign completion delegation')
    return expected['task'], expected['index']


def append(progress, prefix, record):
    subprocess.run(['bash', str(Path(__file__).resolve().with_name('append-progress.sh')), str(progress)],
                   input=prefix + json.dumps(record) + '\n', text=True, check=True)


def delegate_move(plan, progress, task_id):
    parsed = tasks(plan)
    dispatch_state(plan, Path(progress), parsed)
    record = move_record(plan, parsed)
    if record['task'] != task_id or any(not done for t in parsed for i, done in enumerate(t['checks'])
                                      if (t['id'], i) != (task_id, record['index'])):
        raise ValueError('only the final move checkbox may remain pending')
    if not delegation(plan, progress, parsed):
        append(progress, '[completion-move-delegated] ', record)
    return {'state': 'delegated', **record}


def complete_move(plan, progress, destination):
    plan, destination = Path(plan).resolve(), Path(destination).resolve(strict=True)
    if plan.exists() or destination != plan.parent / 'completed' / plan.name:
        raise ValueError('move destination not verified')
    parsed = tasks(destination)
    dispatch_state(plan, Path(progress), parsed)
    delegated = delegation(plan, progress, parsed)
    if any(not done for t in parsed for i, done in enumerate(t['checks']) if (t['id'], i) != delegated):
        raise ValueError('other task checks remain pending')
    if delegated is None:
        return {'state': 'no-delegation'}
    # Update only the recorded final checkbox, after the actual filesystem move.
    with destination.open(newline='') as stream:
        text = stream.read()
    task = next(t for t in parsed if t['id'] == delegated[0])
    position = task['check_positions'][delegated[1]]
    if text[position] != ' ':
        raise ValueError('delegated checkbox is not pending')
    with destination.open('w', newline='') as stream:
        stream.write(text[:position] + 'x' + text[position + 1:])
    append(progress, '[completion-move-fulfilled] ', {'plan': str(plan), 'destination': str(destination)})
    return {'state': 'fulfilled'}


def check_move(plan, progress):
    parsed = tasks(plan)
    dispatch_state(plan, Path(progress), parsed)
    delegated = delegation(plan, progress, parsed)
    if any(not done for t in parsed for i, done in enumerate(t['checks']) if (t['id'], i) != delegated):
        raise ValueError('other task checks remain pending')
    return {'state': 'ready', 'completion_move_pending': delegated is not None}


def render(template, context):
    text = Path(template).read_text()
    if re.search(r"CLAUDE_PLUGIN|\$\{user_config\.|\$ARGUMENTS", text):
        raise ValueError("legacy unresolved prompt contract")
    values = json.loads(Path(context).read_text())
    if not isinstance(values, dict):
        raise ValueError("prompt context must be a JSON object")
    required = set(re.findall(r"\{\{([A-Z_]+)\}\}", text))
    missing = required - values.keys()
    if missing:
        raise ValueError("missing prompt values: " + ", ".join(sorted(missing)))
    for key in required:
        if not isinstance(values[key], str):
            raise ValueError("prompt values must be strings: " + key)
        if key.endswith(("_PATH", "_DIR", "_DIRECTORY")) or key == "RESOLVE_SCRIPT":
            if not Path(values[key]).is_absolute():
                raise ValueError("absolute path required: " + key)
    # Single pass: user rules and paths are data, never recursively interpolated.
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m[1]], text)


def main():
    try:
        command, *args = sys.argv[1:]
        if command == "select" and len(args) in (1, 2):
            print(json.dumps({"plan": select(*args)}))
        elif command == "next" and len(args) == 3:
            print(json.dumps(next_task(args[0], args[1], int(args[2]))))
        elif command == "render" and len(args) == 2:
            print(render(*args))
        elif command == 'delegate-move' and len(args) == 3:
            print(json.dumps(delegate_move(*args)))
        elif command == 'complete-move' and len(args) == 3:
            print(json.dumps(complete_move(*args)))
        elif command == 'check-move' and len(args) == 2:
            print(json.dumps(check_move(*args)))
        else:
            raise ValueError(__doc__)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("task-loop: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
