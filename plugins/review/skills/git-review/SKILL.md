---
name: git-review
description: Interactive git diff annotation review using revdiff. Activates on "git review", "review changes", "review my changes", "annotate changes", "interactive review".
---

# Git Review

Interactive annotation-based code review with friendly file headers, function
context and source-line mapping. Keep the upstream annotation → proposed fix →
user approval → edit → fresh review loop. Never infer approval from empty stdout.

## Step 1: Select and run the review

Resolve this loaded skill's base directory with `realpath`; the script is
`<canonical-skill-base>/scripts/git-review.py`. Run from the user's repository.
Arguments from a slash command are data, not a shell command; preserve quoted
paths/refs. Do not launch UI without the user's selected terminal backend/target.

- No ref: staged + unstaged tracked changes against HEAD, plus untracked files;
  if none exist, current branch vs detected default branch (merge-base diff).
- `<base>`: `<base>...HEAD`; `--branch <target>`: `<base>...<target>` without checkout.
  Explicit two/three-dot ranges are preserved. Ref review excludes worktree changes.
- `--staged` selects index only; `--unstaged` selects tracked worktree vs index.
  Neither may be combined with ref/branch selection.

Create a unique caller-owned directory under `/tmp/opencode/`; choose **new**
`annotations.md` and `status.json` paths inside it. Example (only after selection):

```text
python3 <script> [base] [--branch target | --staged | --unstaged]
  --output <new-annotations.md> --status <new-status.json>
  --terminal kitty-window
```

Terminal options use the Task 5 launcher unchanged:
- `kitty-window` (independent Kitty, no remote control/config change) or `foot-window`;
- `kitty-overlay --kitty-socket <existing-address> --kitty-window-id <positive-id>`;
- `tmux --tmux-socket <socket> --tmux-client <attached-client> --tmux-pane <%N>`.
  All three target flags are required; never select a random client or server env.
Optional client display overrides: `--wayland-display`, `--xdg-runtime-dir`, `--display`.
`--timeout` defaults to 1800 seconds; allow a longer tool timeout or use background
execution and wait for actual completion. No automatic fallback to another UI.

## Step 2: Read annotations and snapshot context

Read actual exit status, JSON status and the separate annotation file. stdout is
not a result channel. Missing/malformed handoff is failure, never clean.

- `annotations`: revdiff comments refer to `review.diff` **display rows**, NOT
  source rows. `status.snapshot_text` is the exact cleaned diff the user saw;
  `status.line_map[row - 1]` gives repository-relative path, kind and old/new
  source coordinates. Resolve paths from `status.repository`, not the tool cwd.
  Deleted lines have only old coordinates; headers/binary metadata have no source
  line. Read the actual source/context before proposing edits; never blindly
  apply numbers from a deleted line or header as current source positions.
- `needs-confirmation`: revdiff 1.13 returns the same empty output for `q` and
  discard `Q`. Ask **Review complete / Open again / Leave unfinished**. Earlier
  approval to start review or fix code does not answer this new question.
- `no-changes`: nothing in the selected diff; report this, not “review approved”.
- `skipped`: explicit `PLANNING_DISABLE_REVDIFF`; report skipped, leave retry possible.
- `failed`, `cancelled`, `stale`, nonzero exit: show diagnostics, leave unfinished.
  Never apply annotations from these runs or infer completion from empty output.

## Step 3: Propose fixes, then obtain approval

Before using annotations, and again before edits or accepting Review complete:

```text
python3 <script> --check-status <status.json>
```

This recomputes the original selection, resolved refs and index/worktree evidence.
Nonzero means the reviewed snapshot is no longer current: regenerate/reopen and
do not apply old line numbers. A clean check is not itself approval.

List each comment with its mapped file/code area, describe the intended fix and
obtain user approval **before** changing code. Use supported native Plan selection
if helpful; do not call EnterPlanMode or start exec automatically. Ambiguous or
unmapped comments require clarification, not guessed edits.

## Step 4: Address and repeat

After approval and a fresh snapshot check, edit real source files and read back
the result. Regenerate review with the same selected mode/ref/terminal and fresh
handoff paths. New annotations repeat the proposal/approval loop. Empty results
repeat the three-way question; Open again opens a fresh snapshot, Leave unfinished
does not approve, commit or start implementation. Only a fresh explicit Review
complete with a still-current snapshot ends the review.

Read annotations/status before deleting only the caller's own handoff directory.
Internal snapshot/history/terminal files are unique and automatically cleaned;
there is no persistent upstream editor tracking repo and no `--clean` operation.

## Requirements and checks

Git, Python 3, revdiff 1.13 and the selected terminal executable. Run embedded
checks with `python3 <script> --test`; integration tests and the pending human
acceptance procedure are in `tests/smoke/git-review.md`. Installed configuration
is not changed by this workflow.
