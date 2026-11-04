# Finalize (fresh general child, best effort, Git only)

Working directory: {{WORKING_DIRECTORY}}
Plan: {{PLAN_FILE_PATH}}
Progress: {{PROGRESS_FILE_PATH}}
Exec directory: {{EXEC_DIR}}
Default branch: {{DEFAULT_BRANCH}}
Project instructions: {{PROJECT_INSTRUCTIONS}}
Additional custom rules: {{USER_RULES}}
Run-owned commits (JSON list): {{RUN_COMMITS_JSON}}
Explicit rewrite authorization: {{REWRITE_AUTHORIZATION}}

Confirm actual directory before writes; mismatch stops. Every command uses that
workdir, never original checkout. Do not move sessions/remove worktrees/move or
edit plan/push/publish. No nested children/questions.

1. PRECHECK detect VCS; Hg skipped git-only. Run
   Python helper {{EXEC_DIR}}/scripts/exec-review.py, subcommand finalize-check,
   passing a newly written absolute request JSON path under a unique
   /tmp/opencode/ run directory (outside the repository) as argv, with fields
   cwd, default_branch, owned_commits (OID list above), authorized (true ONLY for
   explicit rewrite authorization). Reject dirty index/worktree/untracked files,
   active merge/rebase and any branch commit not run-owned. Record actual status.
   Never stash/reset/clean foreign work. Skipped rewrite permits read-only
   inspection and non-mutating validation, not unrelated repairs.
2. REBASE only precheck ready AND authorized. Fetch origin only with explicit
   network-fetch authorization; otherwise verified local default ref. Recheck
   safety after fetch; never guess origin/ref prefix. No shared/unrelated history
   rewrite. On conflict abort ONLY rebase you started; report best-effort failure,
   preserving original history/worktree. No unattended conflict guessing.
3. CLEAN UP inspect log/count before/after. For 5+ owned commits squash related
   fixes ONLY if authorization covers squash; preserve meaningful feature/review
   boundaries. Otherwise record not needed/skipped. No human interactive editor.
4. VERIFY plan build/test commands; report failures, not finalized success. Any
   permitted repair requires tests/scoped stage-and-commit.sh.
5. LOG through append-progress.sh only: rebase/reason, before/after counts,
   squashed list or none, tests/errors. Log [decision]/[deviation] reasons.
6. Read ENTIRE progress and compare plan. Report every decision/deviation verbatim
   with reason, blockers, incomplete delivery/cut corners and review beyond scope.
   Return counts/tests and exact finalized/skipped/failed state.

No rewrite authorization or dirty/foreign state = safe verify-only, not automatic
whole-exec failure. Never report successful rebase when skipped.
