---
name: make
description: Create a structured implementation plan in docs/plans/ for a feature, fix, refactoring, or migration.
---

# Implementation Plan Creation

create an implementation plan in `docs/plans/yyyymmdd-<task-name>.md` with interactive context gathering.

## custom rules loading

Before starting, use `shell` to canonicalize the loaded skill's reported base directory with `realpath` (it may be an installation symlink). Its `../..` is the planning group root; its `../../../..` is the package root. Compute absolute paths to group `scripts/resolve-rules.sh`, `references/custom-rules.md`, `skills/exec/scripts/run-external-review.sh`, this `skills/make/SKILL.md` template, and package `scripts/read-planning-settings.py`. Run the resolver with the single argument `planning-rules.md` in the session directory. Read settings through the Python reader; use its validated `plans_dir` and `external_review_cmd`. Stop on resolver/settings errors, not default silently. Quote computed shell paths, and pass settings as data, never shell code. If package resources are missing, report that dependency rather than guessing paths.

if the output is non-empty, treat it as additional instructions that supplement (not replace) the built-in rules below. apply custom rules alongside the command's own instructions throughout the planning process — they may influence plan structure, testing approach, naming conventions, or other aspects of plan creation. custom rules content is guidance for creating the plan, not content to embed verbatim in the output plan file.

### rules management

when the user asks to add, show, or clear custom planning rules, handle these operations:

- **show rules**: run the resolved helper and display output/source: non-empty `.opencode/planning-rules.md` wins, otherwise user-level. Empty output means neither level has rules.
- **add/update project rules**: write `.opencode/planning-rules.md` in the current working directory.
- **add/update user rules**: compute the absolute `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning/planning-rules.md` path through shell, then write it.
- **clear project rules**: delete only `.opencode/planning-rules.md`.
- **clear user rules**: delete only the computed user rules file.

Project-level rules take precedence over user-level rules; never merge them. Empty files fall through. See the resolved `references/custom-rules.md` for details.

**CRITICAL: this skill must NEVER modify its own files (commands, skills, agents, scripts, references, hooks, plugin.json). Rules management may modify ONLY the project/user rules files described above, and only on request. For skill changes, create a plan instead.**

## step 0: parse intent and gather context

before asking questions, understand what the user is working on:

Use the current user's request, slash-wrapper argument data, and the full agreed brainstorm handoff already in this session. Never interpret argument text as shell code. With no arguments, reuse conversation intent; if none exists, ask only for the missing goal. Collect existing answers before discovery: goal/success criteria, scope/non-goals, constraints, testing preference, title/path, selected approach, validated design, decisions and next/review/implementation choices. Do not ask again or re-propose rejected approaches. For an existing plan, resolve its absolute path, verify it is a readable file, read it before edits, and preserve agreed content; missing/ambiguous paths require clarification, not silently choosing or overwriting another plan.

Classify the current action first: create, revise, review-only, or rules management. The latest explicit action overrides earlier next-step choices. **Review-only of an existing plan skips plan creation (step 2) and all commits/implementation.** Go directly to the selected review branch of step 3 using that existing absolute path; do not create a duplicate dated plan, even if the old handoff originally requested creation. A denied/failed reviewer leaves every file and HEAD unchanged unless the user separately approved an edit/commit. Revision changes only the requested parts of the same file. Rules-only requests do not start plan creation.

1. **parse user's command arguments** to identify intent:
   - "add feature Z" / "implement W" → feature development
   - "fix bug" / "debug issue" → bug fix plan
   - "refactor X" / "improve Y" → refactoring plan
   - "migrate to Z" / "upgrade W" → migration plan
   - generic request → explore current work

2. **gather relevant context quickly** — use direct `read`, `glob`, `grep` calls, NOT an Explore agent. keep discovery under 30 seconds:

   **for feature development:**
   - glob for files matching the feature area (e.g., `**/*auth*`, `**/*cache*`)
   - read 1-3 most relevant files to understand existing patterns
   - check project structure with a quick `ls` of key directories

   **for bug fixing:**
   - grep for error messages or function names mentioned in the request
   - read the specific file(s) involved
   - check `git log --oneline -5` for recent changes

   **for refactoring/migration:**
   - glob for files matching the area being refactored
   - read 2-3 key files to understand current structure
   - grep for imports/references to identify dependencies

   **for generic/unclear requests:**
   - check `git status` and `git log --oneline -5`
    - read README.md or applicable AGENTS.md for project overview
   - `ls` the top-level directory structure

   **CRITICAL: do NOT launch an Explore agent or read more than 5 files in this step. the goal is a quick scan, not exhaustive analysis. if more context is needed, ask the user in step 1.**

3. **synthesize findings** into a brief context summary (3-5 bullet points):
   - what the project is and primary language/framework
   - which files/areas are relevant to the request
   - key patterns or conventions observed

## step 1: present context and ask focused questions

Show the discovered context, then ask only unanswered questions **one at a time** using `question`. Treat every item below as a field to fill, not a mandatory question when its answer is already agreed:

"based on your request, i found: [context summary]"

**ask questions one at a time (do not overwhelm with multiple questions):**

1. **plan purpose**: use `question` - "what is the main goal?"
   - provide multiple choice with suggested answer based on discovered intent
   - wait for response before next question

2. **scope**: use `question` - "which components/files are involved?"
   - provide multiple choice with suggested discovered files/areas
   - wait for response before next question

3. **constraints**: use `question` - "any specific requirements or limitations?"
   - can be open-ended if constraints vary widely
   - wait for response before next question

4. **testing approach**: use `question` - "do you prefer TDD or regular approach?"
   - options: "TDD (tests first)" and "Regular (code first, then tests)"
   - store preference for reference during implementation
   - wait for response before next question

5. **plan title**: use `question` - "short descriptive title?"
   - provide suggested name based on intent

after all questions answered, synthesize responses into plan context.

## step 1.5: explore approaches

once the problem is understood, propose implementation approaches:

1. **propose 2-3 different approaches** with trade-offs for each
2. **lead with recommended option** and explain reasoning
3. **present conversationally** - not a formal document yet

example format:
```
i see three approaches:

**Option A: [name]** (recommended)
- how it works: ...
- pros: ...
- cons: ...

**Option B: [name]**
- how it works: ...
- pros: ...
- cons: ...

which direction appeals to you?
```

Use `question` to select the preferred approach only if not already agreed.

**skip this step** if:
- the implementation approach is obvious (single clear path)
- user explicitly specified how they want it done
- it's a bug fix with clear solution

## step 2: create plan file

Check the configured `plans_dir` (default `docs/plans/`) for existing files, then create the dated plan there, using current date and agreed title. Resolve and retain its absolute path. Respect an explicitly agreed path and never overwrite an unrelated existing file. The template below uses the default directory; adapt paths to the actual agreed location.

### plan structure

```markdown
# [Plan Title]

## Overview
- clear description of the feature/change being implemented
- problem it solves and key benefits
- how it integrates with existing system

## Context (from discovery)
- files/components involved: [list from step 0]
- related patterns found: [patterns discovered]
- dependencies identified: [dependencies]

## Development Approach
- **testing approach**: [TDD / Regular - from user preference in planning]
- complete each task fully before moving to the next
- make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
  - tests are not optional - they are a required part of the checklist
  - write unit tests for new functions/methods
  - write unit tests for modified functions/methods
  - add new test cases for new code paths
  - update existing test cases if behavior changes
  - tests cover both success and error scenarios
- **CRITICAL: all tests must pass before starting next task** - no exceptions
- **CRITICAL: update this plan file when scope changes during implementation**
- run tests after each change
- maintain backward compatibility

## Testing Strategy
- **unit tests**: required for every task (see Development Approach above)
- **e2e tests**: if project has UI-based e2e tests (Playwright, Cypress, etc.):
  - UI changes → add/update e2e tests in same task as UI code
  - backend changes supporting UI → add/update e2e tests in same task
  - treat e2e tests with same rigor as unit tests (must pass before next task)
  - store e2e tests alongside unit tests (or in designated e2e directory)
  - example: if task implements new form field, add e2e test checking form submission

## Progress Tracking
- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix
- update plan if implementation deviates from original scope
- keep plan in sync with actual work done

## Solution Overview
- high-level approach and architecture chosen
- key design decisions and rationale
- how it fits into the existing system

## Technical Details
- data structures and changes
- parameters and formats
- processing flow

## What Goes Where
- **Implementation Steps** (`[ ]` checkboxes): tasks achievable within this codebase - code changes, tests, documentation updates
- **Post-Completion** (no checkboxes): items requiring external action - manual testing, changes in consuming projects, deployment configs, third-party verifications

## Implementation Steps

<!--
Task structure guidelines:
- Each task = ONE logical unit (one function, one endpoint, one component)
- Use specific descriptive names, not generic "[Core Logic]" or "[Implementation]"
- Each task MUST have a **Files:** block listing files to Create/Modify (before checkboxes)
- Aim for ~5 checkboxes per task (more is OK if logically atomic)
- **CRITICAL: number ALL tasks with concrete sequential integers** - the two trailing tasks below are shown as "Task N-1" and "Task N" where N is a PLACEHOLDER for the total task count, NOT literal text. Substitute real numbers continuing the sequence from your last implementation task (e.g. with 14 implementation tasks they become "Task 15: Verify acceptance criteria" and "Task 16: ... Update documentation"). NEVER write the literal strings "Task N-1" or "Task N" into the plan.
- **CRITICAL: Each task MUST end with writing/updating tests before moving to next**
  - tests are not optional - they are a required deliverable of every task
  - write tests for all NEW code added in this task
  - write tests for all MODIFIED code in this task
  - include both success and error scenarios in tests
  - list tests as SEPARATE checklist items, not bundled with implementation

Example (NOTICE: Files block + tests as separate checklist items):

### Task 1: Add password hashing utility

**Files:**
- Create: `src/auth/hash`
- Create: `src/auth/hash_test`

- [ ] create `src/auth/hash` with HashPassword and VerifyPassword functions
- [ ] implement bcrypt-based hashing with configurable cost
- [ ] write tests for HashPassword (success + error cases)
- [ ] write tests for VerifyPassword (success + error cases)
- [ ] run tests - must pass before task 2

### Task 2: Add user registration endpoint

**Files:**
- Create: `src/api/users`
- Modify: `src/api/router`
- Create: `src/api/users_test`

- [ ] create `POST /api/users` handler in `src/api/users`
- [ ] add input validation (email format, password strength)
- [ ] integrate with password hashing utility
- [ ] write tests for handler success case with table-driven cases
- [ ] write tests for handler error cases (invalid input, missing fields)
- [ ] run tests - must pass before task 3
-->

### Task 1: [specific name - what this task accomplishes]

**Files:**
- Create: `exact/path/to/new_file`
- Modify: `exact/path/to/existing`

- [ ] [specific action with file reference - code implementation]
- [ ] [specific action with file reference - code implementation]
- [ ] write tests for new/changed functionality (success cases)
- [ ] write tests for error/edge cases
- [ ] run tests - must pass before next task

<!-- replace "N-1" and "N" below with the actual next sequential numbers continuing from your last implementation task - do NOT emit the literal letter N -->
### Task N-1: Verify acceptance criteria
- [ ] verify all requirements from Overview are implemented
- [ ] verify edge cases are handled
- [ ] run full test suite: `<project test command>`
- [ ] run e2e tests if project has them: `<project e2e test command>`
- [ ] verify test coverage meets project standard

### Task N: [Final] Update documentation
- [ ] update README.md if needed
- [ ] update applicable AGENTS.md if new patterns discovered
- [ ] move this plan to `docs/plans/completed/`

## Post-Completion
*Items requiring manual intervention or external systems - no checkboxes, informational only*

**Manual verification** (if applicable):
- manual UI/UX testing scenarios
- performance testing under load
- security review considerations

**External system updates** (if applicable):
- consuming projects that need updates after this library change
- configuration changes in deployment systems
- third-party service integrations to verify
```

## step 3: next steps

after creating the file, tell user: "created plan: `docs/plans/yyyymmdd-<task-name>.md`"

Then use `question`, unless a next action was already chosen (honor it without asking again):

```json
{
  "questions": [{
    "question": "Plan created. What's next?",
    "header": "Next step",
    "options": [
      {"label": "Interactive review", "description": "Review the full plan with revdiff in a selected separate terminal window, Kitty overlay or tmux popup"},
      {"label": "Auto review", "description": "Automated analysis by the plan-review agent or the external reviewer (codex by default)"},
      {"label": "Implement", "description": "Commit plan and start implementing"},
      {"label": "Done", "description": "Commit plan, no further action"}
    ],
    "multiple": false
  }]
}
```

- **Interactive review**: follow **Explicit plan annotation review** below, then return to this choice only when the user confirms completion. Keep pending/skipped/failed review retryable; never imply approval or automatically implement after those states.
- **Auto review**: ask which reviewer to use:
  ```json
  {
    "questions": [{
      "question": "Which reviewer?",
      "header": "Reviewer",
      "options": [
        {"label": "Plan-review agent", "description": "Internal agent checks problem definition, over-engineering, testing and conventions"},
        {"label": "External reviewer", "description": "Send the plan to the configured external_review_cmd, or codex when unset"}
      ],
      "multiple": false
    }]
  }
  ```
   Honor an already selected reviewer without another question. Launch using `subagent` with `agent`, `description`, `prompt`; do not set a model unless the user selected one. Children have fresh context: fully render the prompt with absolute working directory, readable absolute plan path, canonical template/helper paths, applicable AGENTS.md and explicitly loaded local instructions, resolved planning rules and their source (or none), agreed goal/design/constraints/decisions, review focus and the exact validated external command as data (empty string means Codex). No unresolved placeholders. Tell reviewers to remain read-only, not ask the user, not launch children, and return failure for missing context/files. If delegation is unavailable or denied, report failed and keep review retryable; never simulate a completed reviewer.
   - **Plan-review agent**: `subagent({agent:"plan-review", description:"Review implementation plan", prompt: fullyRenderedContext})`. Return its findings/assessment to the user; apply only agreed fixes and retain its verdict.
   - **External reviewer**: `subagent({agent:"external-plan-review", description:"External plan review", prompt: fullyRenderedContext})`. It returns a status line and, when there are findings, findings verbatim.
    - skipped or failed: show the status line to the user.
    - no issues found: tell the user.
     - findings: show every finding with your assessment (including conflicts with agreed decisions). Ask which to apply using `question` with `multiple: true`: at most 3 findings plus "None of these" per question, at most 4 questions per call, further calls for the rest. Do not drop findings. If the user already selected fixes, apply only those without asking again. Read back the revised file to confirm edits persisted. On re-review pass the same absolute path with refreshed context, not a stale snapshot.

   After a completed review, ask again with the same options (minus "Auto review"), unless the next action is already agreed. When either reviewer was skipped, failed or denied, keep "Auto review": no completed review happened. The internal plan-review agent needs no external tool. If the user requested review-only and stop, report its status and stop without offering implementation or creating/committing any plan.
- **Implement**: commit plan with message like "docs: add <topic> implementation plan", then ask implementation mode:
  ```json
  {
    "questions": [{
      "question": "Implementation mode?",
      "header": "Mode",
      "options": [
        {"label": "Interactive", "description": "Implement task by task in this session"},
        {"label": "Autonomous", "description": "Load exec in the current session for autonomous execution with reviews"}
      ],
    "multiple": false
    }]
  }
  ```
   Honor an already agreed implementation mode without asking again.
   - **Interactive**: implement task 1 in this session; track plan checkboxes durably and mark completion immediately, not in a batch.
   - **Autonomous**: build the same full handoff plus the absolute existing plan path, validated settings, review results/status and unresolved dependencies, agreed mode/branch/worktree choices; call `skill({"id":"exec"})` in the current session. Do not run slash commands in shell or spawn a fresh orchestrator. Ask only missing execution choices. Exec migration remains Tasks 7–9; do not imply that loading it proves execution ready.
- **Done**: commit plan with message like "docs: add <topic> implementation plan", stop

## Explicit plan annotation review

This section is also the complete review-only route for `/review-plan` and native Plan. Review the supplied existing absolute plan path, never create/commit another plan, run automatic reviewers, or start implementation on this route. Native Plan has no ExitPlanMode hook: after saving, the user invokes `/review-plan <absolute-path>` (switch to a write-capable agent only for agreed fixes if native Plan permissions deny them). Never intercept write/patch calls; the old `plan-review-hook.py` and `plan-annotate.py` are provenance only, not an active V2 route.

1. Canonicalize this loaded skill base with `realpath`; launcher is `../../scripts/launch-plan-review.sh` relative to the canonical base. Resolve/read the supplied plan; ask only for a missing/ambiguous path. Show the exact path to the user. Do not search for a different plan on failure.
2. A nonempty `PLANNING_DISABLE_REVDIFF` (even `0`) is **skipped**, never approval. Otherwise obtain the user's explicit terminal/backend choice before opening UI. Supported choices (`--backend` aliases `--terminal`): **`kitty-window`** (recommended no-tmux route, independent graphical Kitty with builtin defaults, no remote control/configuration), **`foot-window`** (separate Foot window), **`kitty-overlay`** (only with an already available explicit `--kitty-socket <address> --kitty-window-id <positive-id>`), or **`tmux`** (explicit `--tmux-socket <socket> --tmux-client <client> --tmux-pane <%N>`). Existing tuple-only invocations retain tmux compatibility. Never infer overlay/popup targets from server `TMUX`/`KITTY_*`, choose the first client/window, enable remote control, restart terminals, change desktop configuration or silently switch backends. User can obtain tmux tuple with `tmux display-message -p '#{socket_path} #{client_name} #{pane_id}'`; for an already configured Kitty socket use `kitty @ --to <address> ls` and select the intended window ID. If no choice was supplied, offer a separate Kitty window (no setup) or ask for the existing target; leave pending until selected. Separate windows inherit available display env, not terminal identity. If service display env is absent/stale, request current client `WAYLAND_DISPLAY` + `XDG_RUNTIME_DIR` (or X11 `DISPLAY`) and pass explicit `--wayland-display`, `--xdg-runtime-dir` (or `--display`); do not guess a compositor or reconfigure it. An unavailable remote-control socket should suggest `kitty-window`, not configuration changes.
3. Create a unique handoff directory with `mktemp -d /tmp/opencode/plan-review-handoff.XXXXXX`. Run via `shell` with quoted paths/argv (never eval raw arguments): `bash <launcher> <absolute-plan> --output <handoff>/annotations.md --status <handoff>/status.json --terminal kitty-window --exit-code-on-annotations` for the selected no-tmux window, or replace backend/target flags with the user's choice above. Paths/display strings remain individual argv values. Use shell timeout greater than launcher `--timeout` (default 1800 seconds), or launch background and await its actual completion. Do not automatically retry an interrupted tool call as though it succeeded. Launcher stdout is not annotations; read **both** files and retain exit status. If tool/launcher fails or status is missing/malformed, report incomplete review, never clean. Show missing dependencies/target/display errors and offer retry. A successful terminal launch/daemonized launcher exit is not a completed review: the TTY worker must publish actual revdiff exit/output. Window close, missing worker handoff, cancellation and timeout are incomplete. Caller owns handoff cleanup after consuming the files; internal snapshot/UI files are removed by launcher, even after cancellation.
4. `annotations`: read all comments verbatim, bind `annotation_file` basename/line numbers to **status.plan** and **status.snapshot_text**, never cwd. Compare the current file's SHA-256 to `snapshot_sha256` before applying: if changed, rerun instead of applying stale line numbers. Assess comments, apply only requested fixes to that same plan, read back to confirm persistence, then reopen the full updated plan with a fresh handoff directory and the same confirmed target. Report any rejected/ambiguous annotation; do not silently drop it. The snapshot review is full text independent of Git tracking/root, not a working-tree diff.
5. `needs-confirmation`: revdiff 1.13 produces the same empty result for `q`, discard `Q`, and some signals. **Always ask now**, even if earlier intent was approval: use `question` with options **Review complete** (explicit approval of this snapshot), **Open again** (fresh launcher run), **Leave unfinished** (cancel/pending, no approval). A prior Done/Implement choice or exit 0 is not this confirmation. After the answer Review complete, BEFORE accepting it or recording approval, run `python3 <canonical-planning-scripts>/plan-review-launcher.py --check-status <handoff>/status.json`. This rechecks the current bytes/hash against the reviewed snapshot after the wait for user input. Failure or `stale` is not approval: explain the change and reopen fresh review with the same selected terminal. Only explicit Review complete plus successful fresh validation completes interactive review; record the choice and snapshot hash. Open again loops; Leave unfinished stops without commit/implementation on the review-only route.
6. `skipped`, `failed`, `cancelled`, `stale`, missing status and unexpected exit never complete review. Do not recover history as an approved result. Annotation exit 10 is accepted only when `--exit-code-on-annotations` was passed and output exists; launcher records actual revdiff exit separately from terminal exit. A tool cancellation is not successful empty review. After reporting results and persisting necessary context, remove only this invocation's handoff files/directory.

## execution enforcement

**CRITICAL testing rules during implementation:**

1. **after completing code changes in a task**:
   - STOP before moving to next task
   - add tests for all new functionality
   - update tests for modified functionality
   - run project test command
   - mark completed items with `[x]` in plan file

2. **if tests fail**:
   - fix the failures before proceeding
   - do NOT move to next task with failing tests
   - do NOT skip test writing

3. **only proceed to next task when**:
   - all task items completed and marked `[x]`
   - tests written/updated
   - all tests passing

4. **plan tracking during implementation**:
   - update checkboxes immediately when tasks complete
   - add ➕ prefix for newly discovered tasks
   - add ⚠️ prefix for blockers
   - modify plan if scope changes significantly

5. **on completion**:
   - verify all checkboxes marked
   - run final test suite
   - move plan to `docs/plans/completed/`
   - create directory if needed: `mkdir -p docs/plans/completed`

6. **partial implementation exception**:
   - if a task provides partial implementation where tests cannot pass until a later task:
     - still write the tests as part of this task (required)
     - add TODO comment in test code explaining the dependency
     - mark the test checkbox as completed with note: `[x] write tests ... (fails until Task X)`
     - do NOT skip test writing or defer until later
   - when the dependent task completes, remove the TODO comment and verify tests pass

this ensures each task is solid before building on top of it.

## key principles

- **one question at a time** - do not overwhelm user with multiple questions in a single message
- **multiple choice preferred** - easier to answer than open-ended when possible
- **DRY, YAGNI ruthlessly** - avoid unnecessary duplication and features, keep scope minimal (but prefer duplication over premature abstraction when it reduces coupling)
- **lead with recommendation** - have an opinion, explain why, but let user decide
- **explore alternatives** - always propose 2-3 approaches before settling (unless obvious)
- **duplication vs abstraction** - when code repeats, ask user: prefer duplication (simpler, no coupling) or abstraction (DRY but adds complexity)? explain trade-offs before deciding
