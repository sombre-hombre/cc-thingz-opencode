# Planning Plugin Usage

The planning plugin has four components: make (plan creation), exec (autonomous execution), plan-review (quality review agent), and external-plan-review (sends a plan to the external review tool).

## Make — `/make`, `@make`

### Triggers
- `/make <description>` — create an implementation plan
- invoked automatically by brainstorm when user picks "Write plan"

### Workflow
1. **Step 0** — parses intent (feature, bug fix, refactor, migration) and explores codebase for context
2. **Step 1** — asks focused questions one at a time: goal, scope, constraints, testing approach, title
3. **Step 1.5** — proposes 2-3 implementation approaches with trade-offs (skipped if obvious)
4. **Step 2** — creates plan file at `docs/plans/yyyymmdd-<task-name>.md`
5. **Step 3** — offers next steps: interactive review, auto review (plan-review agent or external reviewer), implement, or done

### Examples
```
/make add user authentication
/make fix the race condition in the connection pool
/make refactor the middleware stack
/make add my Go testing rules to user-level planning rules
```

### Plan File Structure
- Overview, Context, Development Approach, Testing Strategy
- Implementation Steps with `### Task N:` sections
- Each task has `**Files:**` block and `[ ]` checkboxes
- Progress tracking with `[x]`, `➕`, `⚠️` markers

## Exec — `/exec`, `@exec`

### Triggers
- `/exec [plan-file]` — execute a plan autonomously
- "exec", "execute plan", "run plan"

### Workflow
1. Resolves plan file (from argument or picks from `docs/plans/`)
2. Asks about worktree isolation (worktree vs current directory)
3. Creates a feature branch
4. Executes tasks sequentially — one subagent per task, commits after each
5. Runs multi-phase review: comprehensive (iteration 1) then critical re-check loop → code smells → external review → critical-only
6. Optional finalize: verify; rewrite only with explicit authorization and run-owned commit evidence
7. Stats summary: aggregate per-phase tokens/duration + git diff stats and report

### Configuration
Optional JSON settings: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning/settings.json`. Missing file uses defaults; malformed values stop the workflow.

| Key | Default | Description |
|-----|---------|-------------|
| `external_review_cmd` | *(empty — falls back to codex)* | external review tool command, for code review in exec and plan review in make; prompt appended as final argv, findings on stdout |
| `task_retries` | `1` | retries for failed tasks |
| `review_iterations` | `5` | max fix-and-recheck cycles |
| `external_review_iterations` | `10` | max external review iterations |
| `finalize_enabled` | `true` | run rebase + squash phase |
| `plans_dir` | `docs/plans` | directory for plan files |

### Customization
Prompts and agent definitions use a three-layer override chain:
1. Project: `.opencode/exec-plan/prompts/` and `.opencode/exec-plan/agents/`
2. User: `<config>/data/cc-thingz/planning/prompts/` and `<config>/data/cc-thingz/planning/agents/`
3. Bundled defaults

Nothing is copied automatically. Inspect historical overrides before migration: old copies can shadow new defaults. Never delete user overrides automatically.

Use the canonical exec skill's `scripts/customize-file.sh <relative-file>` to copy only the selected default to project overrides, or add `--user` for user data. Existing files are never overwritten. See `custom-rules.md` for rules precedence. Overrides must use the V2 double-brace template contract, not historical tool schemas.

### Customization patterns

- *Route review fanout to named specialists.* Override `prompts/review.md` in the main orchestrator; use only actually registered V2 agents, with explicit context and no nested fanout.
- *Delegate to an existing skill.* An override may load another actually registered skill and follow it inline; include its full context. Optional smells/finalizer skills are not supplied by this package. Never execute slash text in shell or assume an unregistered ID exists.

### Subagent constraint

V2 general children cannot spawn children. The main orchestrator reads `prompts/review.md` as a playbook and launches the five specialists with `subagent({agent:"general",description,prompt})`. Leaf task/fixer/finalizer/stats prompts and agent templates receive complete explicit context. Custom parallel fanout stays in the main session.

## Plan-Review — agent

### Triggers
- launched by make's "Auto review" option when the user picks "Plan-review agent"
- usable as `subagent({agent:"plan-review",description,prompt})` from the main session

### What It Checks
- problem definition and solution correctness
- scope creep and over-engineering
- testing requirements and coverage
- task granularity and ordering
- convention adherence (applicable AGENTS.md, explicitly connected instructions and custom rules)

### Output
Structured report with severity-rated findings:
- Critical Issues, Important Issues, Minor Issues
- Over-Engineering Concerns
- Testing Coverage Assessment
- Verdict: APPROVE or NEEDS REVISION

## External-Plan-Review — agent

### Triggers
- launched by make's "Auto review" option when the user picks "External reviewer"

### What It Does
- sends the plan to `external_review_cmd`, or codex when unset, through exec's `run-external-review.sh`
- the reviewer reads the plan, applicable AGENTS.md/explicit instructions and the code it names, and reports wrong assumptions, missing steps, over-engineering and ordering problems
- one pass; make assesses each finding and revises the plan for the ones the user selects

### Output
A status line (`N findings`, `no issues found`, `skipped`, or `failed`) and the findings verbatim.

## Interactive Review

After saving a plan, make offers an explicit **revdiff** step. `/review-plan <absolute-path>` uses the same review-only route, including plans saved by native Plan. See make's **Explicit plan annotation review** section for the full loop.

Select the backend explicitly: `/review-plan "<absolute-path>" --terminal kitty-window` opens an independent Kitty window without tmux or remote-control setup; `foot-window` uses an installed Foot executable. Separate windows inherit available graphical display environment; if the shared service has stale/missing values, supply the current client's `--wayland-display <value> --xdg-runtime-dir <path>` (or `--display <X11-display>`). Do not guess these or change desktop settings. For an already configured Kitty remote-control socket use `--terminal kitty-overlay --kitty-socket <address> --kitty-window-id <positive-id>`. For tmux retain `--terminal tmux` and explicit socket, attached client and exact `%N` pane. Server `TMUX`/`KITTY_*` never choose a target; no silent backend fallback occurs. Obtain user consent for the selected window before opening UI.

Full-plan snapshots work for untracked, committed and external plans. Annotations and JSON status are separate files; line numbers map to the absolute path and snapshot hash in status, not the current directory. Actual TTY worker status is required even when a terminal launcher exits successfully/daemonizes. Closing a window without handoff, cancellation and timeout cannot approve a review. See `tests/smoke/plan-review.md` in the source checkout for reproduction and remaining human acceptance.

Apply requested annotations, read back the plan, then reopen a fresh snapshot. Empty successful revdiff 1.13 output is **needs-confirmation**, never approval: ask **Review complete / Open again / Leave unfinished**. Missing dependencies/target, errors, cancellation and explicit disable do not complete review. `PLANNING_DISABLE_REVDIFF` means skipped, even when its value is `0`.

The old `plan-review-hook.py`, `plan-annotate.py` and Claude hook metadata remain only as upstream provenance. There is no active editor fallback, ExitPlanMode emulation or file-write interception in V2.
