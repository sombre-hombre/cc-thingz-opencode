# Fixer prompt (fresh general child)

Working directory: {{WORKING_DIRECTORY}}
Plan: {{PLAN_FILE_PATH}}
Progress: {{PROGRESS_FILE_PATH}}
Exec directory: {{EXEC_DIR}}
Phase: {{REVIEW_PHASE}}
Project instructions: {{PROJECT_INSTRUCTIONS}}
Additional custom rules: {{USER_RULES}}

Confirm actual session directory before writes; mismatch stops. Use explicit
working directory for every shell/helper/VCS call. Never move sessions or touch
original checkout in worktree mode. No nested children. No human available:
do not ask questions/pause for input. Follow AGENTS.md, explicitly loaded rules,
lint and dominant patterns. When 50/50 choose smaller reversible option, log why.

Code review found the following FULL, UNFILTERED issues and diagnostics:
<findings>
{{FINDINGS_LIST}}
</findings>

1. VERIFY every finding against actual code with 20–30 lines of context. Classify
   CONFIRMED or FALSE POSITIVE with evidence. Reviewer failure is not clean
   coverage; report it separately. Do not discard solely as pre-existing,
   out-of-scope or architectural. Duplicates can share a fix; account for every
   original finding. Fixer, not parent, decides false positives/already mitigated.
2. FIX all confirmed issues, add missing tests. Preserve unrelated work/staged
   paths. Overlapping foreign changes that cannot safely separate are blockers.
3. VALIDATE plan commands (Validation Commands/Testing Strategy), build/tests.
   Fix failures and rerun. Never commit broken code. Unavailable checks remain
   blockers, not passed. Do not edit task checkboxes or move the plan.
4. COMMIT explicitly owned files after validation with Bash helper
   {{EXEC_DIR}}/scripts/stage-and-commit.sh, message
   "fix: address code review findings", followed by owned filenames as argv.
   Quote all paths safely for shell. No broad git add, no push.
5. LOG confirmed/false-positive mapping, fixes, tests and actual commit OID via
   Bash helper {{EXEC_DIR}}/scripts/append-progress.sh with progress path
   {{PROGRESS_FILE_PATH}} as argv, and stdin/message. Never direct append.
   Each judgment/deviation gets its own
   [decision]/[deviation] line with reason for guaranteed completion reporting.
6. REPORT starting FIXES: then each fixed file:line/change, every false positive
   with evidence, validation/commit and unresolved blockers.
