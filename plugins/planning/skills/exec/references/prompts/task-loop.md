# V2 sequential task loop (parent session playbook, not a child prompt)

This replaces upstream exec steps 1–6. Keep all later phases in upstream order:
comprehensive/fixer → smells/fixer → external/fixer → critical/fixer → optional
finalize → stats → completion. After tasks follow `prompts/review-phases.md` from
the main session, unless explicitly requested task-loop only. Task completion
alone never proves review/finalize success. Worktree isolation follows
`prompts/worktree.md` below this references directory, before any branch/progress
creation. Never silently downgrade an isolation request to in-place execution.

## Admission and explicit context

1. Canonicalize the skill tool's base with realpath as EXEC_DIR. PLANNING_DIR is
   canonical `EXEC_DIR/../..`; package root is `PLANNING_DIR/../..`. Set absolute
   WORKING_DIRECTORY from the session and use it explicitly for every shell call.
   If children are unavailable in this session, stop with that blocker; never
   implement code as the parent or launch nested children from general.
2. Resolve PLUGIN_DATA_DIR as `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning`;
   SETTINGS_FILE_PATH is its settings.json. Read `python3 <package-root>/scripts/read-planning-settings.py`;
   keep validated JSON as SETTINGS_JSON. Missing settings use defaults; errors stop.
   External command remains user settings data, never repository-provided code.
3. Read planning rules with `bash <PLANNING_DIR>/scripts/resolve-rules.sh planning-rules.md <PLUGIN_DATA_DIR>`
   in the project workdir. Keep source path/content as USER_RULES, labeled additional
   custom rules; explicitly say none when absent. Include applicable AGENTS.md and
   explicitly loaded local instructions with source paths as PROJECT_INSTRUCTIONS.
   Resolver errors stop. No inherited parent context is assumed in child sessions.
4. Accept a plan path from the current request/handoff as data including spaces.
   Use `python3 <EXEC_DIR>/scripts/task-loop.py select <absolute-project-directory> <plan-path>`.
   Without an explicit path use `select <absolute-settings.plans_dir>` instead.
   It lists only top-level .md files, not completed/. Exactly one is automatic;
   zero/multiple candidates are blockers with candidate list. Interactive parents
   may use V2 question (`questions`, `multiple`) to select; unattended parents stop,
   never guess by filename/mtime. Malformed/missing/unreadable plan is not completion.
   Read the whole admitted plan. Task/Iteration order is source order, fenced
   examples do not count, every task must contain valid checkboxes and unique ID.
5. Run absolute EXEC_DIR/scripts/detect-vcs.sh and detect-branch.sh. Stop on errors.
    Preserve Git/Hg behavior and git-only limits of later phases. Follow the worktree
    playbook now: ask for isolation unless explicitly answered in the current handoff.
    Rebind project/plan/rules paths after moving, before progress or child work.
    For agreed in-place
   execution run `bash <EXEC_DIR>/scripts/create-branch.sh <absolute-plan>`; capture
   branch. Never create branches manually; keep upstream date-prefix naming and
    existing-feature branch behavior. SKIP create-branch.sh in worktree mode (the
    isolated branch already exists). Inspect foreign status before child work;
   never discard or include unrelated staged/unstaged changes.
6. Create a unique run directory with mktemp -d under /tmp/opencode/. Initialize
   `bash <EXEC_DIR>/scripts/init-progress.sh <absolute-run>/progress.txt <absolute-plan> <branch>`.
   Report the absolute path; preserve it for resume, never truncate it. Resume only
   an explicitly selected run with matching plan/branch. Only one parent drives a
   run; never call next while a child is active. Track phase states in progress,
   not task/todo tools: all later phases start pending. Always append using
   EXEC_DIR/scripts/append-progress.sh, never direct writes.

## Ordered loop

Before EACH dispatch run:
`python3 <EXEC_DIR>/scripts/task-loop.py next <absolute-plan> <absolute-progress> <settings.task_retries>`.
This re-reads/validates the plan, selects the first incomplete task and appends a
durable attempt BEFORE launch. Do not call next speculatively or concurrently.

- `failed`: append diagnostics and report failure. STOP; no reviews or plan move.
- `tasks-complete`: all task checkboxes are checked except an explicitly delegated
  final move (`completion_move_pending: true`), which remains pending. Continue to the review
  playbook above unless explicitly requested task-loop only.
- `dispatch`: announce the task number/title and its pending checkboxes. Resolve
  the task prompt ONLY through `bash <EXEC_DIR>/scripts/resolve-file.sh prompts/task.md <PLUGIN_DATA_DIR>`
  with project workdir (project → user → bundled; empty overrides shadow defaults).
  Never seed overrides or construct the chain manually.

Write resolved template and a JSON context in the run directory. Render using
`python3 <EXEC_DIR>/scripts/task-loop.py render <template-file> <context-json>`.
Provide every double-brace slot explicitly: WORKING_DIRECTORY, PLAN_FILE_PATH,
PROGRESS_FILE_PATH, TASK_ID, TASK_TITLE, ATTEMPT, DEFAULT_BRANCH, EXEC_DIR,
PLANNING_DIR, RESOLVE_SCRIPT, PLUGIN_DATA_DIR, SETTINGS_FILE_PATH, SETTINGS_JSON,
PROJECT_INSTRUCTIONS, USER_RULES, PREVIOUS_ERROR. Paths are absolute, settings JSON
is serialized data, missing rules/errors/instructions explicitly none. Resolve
script is absolute EXEC_DIR/scripts/resolve-file.sh. Do not pass unresolved legacy
environment placeholders; legacy overrides must be updated to this slot contract
or fail admission. Single-pass substitution never interpolates inserted user data.

Launch exactly ONE fresh call:
`subagent({agent: "general", description: "Task N: <title> (attempt K)", prompt: <rendered-text>})`.
Do not pass sessionID, background, permission bypass or a model override (unless
the user explicitly selected a model). Await its return BEFORE next dispatch.
Never batch tasks or reuse a child context. General cannot launch children.

After return re-read the plan. Return text is NOT a success signal. Verify the
assigned checkboxes, child validation/progress and explicit commit evidence.
If assigned checks remain unchecked, run this post-child delegation gate:

```bash
python3 <EXEC_DIR>/scripts/task-loop.py check-move <absolute-plan> <absolute-progress>
```

Only exit 0 with state `ready` and `completion_move_pending: true` permits the
exact validated delegated move to remain unchecked. Verify child validation and
commit evidence for all other assigned checks; then continue via next (which
revalidates durable delegation and admits reviews), without retrying the move.
This is pending completion ownership, not evidence that the move happened.
Otherwise append actual errors/denials/remaining blockers and retry using next,
passing full diagnostics in PREVIOUS_ERROR. task_retries is additional attempts:
default 1 means two total; zero means no retry. Failures/denials consume attempts,
as does a crash after dispatch. Maximum 50 total dispatches (including retries),
durably enforced across resume. Exhaustion stops, leaving unmet checks unchecked.
If a tool failed yet boxes changed, stop for reconciliation unless actual tests
and commit evidence verify completion; never trust only a final response.
Structure changes/deleted plan/malformed checks stop, not successful early exit.
Report each verified completion on one line and continue in source order.

## Commit, decisions and terminal move ownership

Children implement only their assigned section, mark only verified checks and
commit explicit owned paths with stage-and-commit.sh (upstream feat: convention).
Do not include foreign changes even within a selected file: overlapping changes
that cannot be separated safely are blockers. Preserve Git/Hg dispatch, no push.
Log autonomous [decision]/[deviation] reasons through append-progress.sh for the
eventual upstream completion report. Manual/network/skipped checks stay unchecked.

No child may move/delete/rename the plan. A terminal move-only checkbox can be
delegated explicitly to completion, recorded as pending there; it is never proof
the move happened. Use `task-loop.py delegate-move PLAN PROGRESS 'Task N'` after
all other checks pass. It validates and records the exact checkbox/plan structure;
arbitrary pending work cannot be delegated. Only completion after all
review/finalize/stats phases may call `move-plan.sh PLAN PROGRESS` once; the optional
progress argument verifies the actual destination and checks the delegated item
there before the move commit, retaining VCS-aware commit/no-op/error behavior.
