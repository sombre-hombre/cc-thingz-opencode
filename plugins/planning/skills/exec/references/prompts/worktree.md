# V2 worktree isolation (parent playbook)

Run this after plan admission and VCS detection, BEFORE create-branch/init-progress
or child dispatch. No Task 9 review/finalize phase is enabled by this playbook.

For Hg preserve upstream behavior: no automatic worktree, stay in the selected
directory; users may prepare `hg share` manually before exec. Report this limitation.
External-review/finalize bundled prompts remain Git-only; no implied Hg translation.

For Git, read current branch and the detected default branch. Unless the current
request/handoff already explicitly answers, use V2 question with `questions` and
`multiple: false`: on default offer Worktree (isolated) / In-place; on feature
offer Move to worktree / Stay here. Explain that isolation creates a NEW branch
from this checkout's exact HEAD, leaving the original feature branch untouched.
Auto mode does not waive the choice. No answer means stop, not an inferred choice.

## Create and move

1. Set SOURCE_DIRECTORY to the absolute source Git root, preserve original absolute
   plan and source HEAD/branch/status. For isolation, the plan MUST be a regular
   committed file inside this root and clean in index and working tree. Untracked,
   staged/modified/missing/external plans stop with the reason: ask the user to commit
   the chosen plan first. Do not auto-commit/stash/copy dirty source. Other dirty
   files are allowed but are NOT copied to the worktree.
2. Choose a new absolute run path outside source, below /tmp/opencode/, with a
   unique name (not an existing directory). Use absolute canonical EXEC_DIR helpers
   with shell workdir SOURCE_DIRECTORY:
   `python3 <EXEC_DIR>/scripts/worktree.py create <SOURCE_DIRECTORY> <absolute-plan> <new-run-path>`.
   Read its JSON and actual exit. It creates `<run>/tree` via
   `git worktree add -b <unique-name> <absolute-tree> <source-HEAD-OID>`.
   Name comes from create-branch --print-name, with a random suffix on collision.
   Never use name-only worktree_create: its implicit canonical HEAD can be wrong.
3. On failure STOP; inspect stderr and `<run>/worktree.json` when present. A partially
   created worktree/branch belongs to this run; preserve it for diagnostics. Never
   delete/reuse another run's path, prune other worktrees, force-remove, switch the
   source branch, or clean foreign changes. Do not retry by changing source HEAD.
4. Move ONLY the current orchestrator session with documented V2 Code Mode:
   `await tools.opencode.session_move({directory: <JSON.directory>})`.
   Do not pass a parent or unrelated sessionID. Await the result and confirm returned
   directory equals JSON.directory. If move fails/denied/returns another directory,
   STOP without dispatch; report retained directory/branch/manifest. Do not claim
   rollback or delete the created tree. A retry must select this manifest explicitly,
   not create an unnoticed second run. Do not move a caller's parent session.
5. Verify real shell `pwd` without workdir override after move, and run
   `python3 <EXEC_DIR>/scripts/worktree.py verify <absolute-manifest> <observed-directory>`.
   On any mismatch STOP. Source guard includes HEAD, branch, porcelain status,
   tracked staged/unstaged diff and nonignored untracked bytes. It is a guard,
   not a filesystem sandbox or protection against concurrent outside writers.
6. Rebind WORKING_DIRECTORY to JSON.directory and PLAN_FILE_PATH to JSON.plan.
   Confirm admitted plan bytes/hash are present there. Keep EXEC_DIR, PLANNING_DIR,
   RESOLVE_SCRIPT, user settings/data and run/progress paths absolute, never rebase
   them through lexical `..`. Re-resolve project overrides/rules and applicable
   instructions from the worktree; uncommitted source overrides are not present.
   Continue task-loop admission at progress initialization, skipping branch creation.

## All subsequent phases

Every shell/helper uses explicit workdir WORKING_DIRECTORY. Every fresh child's
rendered prompt includes absolute working directory, worktree plan, shared progress,
canonical helpers, rules and instructions; no relative helper paths or inherited
parent context. Children must confirm their actual directory before writes; a
mismatch is failure, not permission to edit source. Child sessions inherit the
moved parent Location; parent verifies actual child directory from returned metadata
or native session API before accepting its result. No child may move itself/parent.

Apply this same directory envelope to each future review/fixer/finalizer, not just
tasks. Resolve templates from the WORKTREE override chain. Task 9 still owns their
phase orchestration and rendering; this does not enable those inactive templates.
After each child and at completion run verify again (plan may legitimately change,
but must still exist until terminal completion). Report final session directory,
worktree branch/path and source guard result. Source breach stops further execution.
Do not automatically move back/remove worktree, and never finalize the source branch.
