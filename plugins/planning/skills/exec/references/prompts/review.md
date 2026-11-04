# Review fanout playbook — MAIN SESSION ONLY, not a child prompt

Phase: {{REVIEW_PHASE}}
Working directory: {{WORKING_DIRECTORY}}
Exec directory: {{EXEC_DIR}}
Plan: {{PLAN_FILE_PATH}}
Progress: {{PROGRESS_FILE_PATH}}
Default branch: {{DEFAULT_BRANCH}}
Resolve script: {{RESOLVE_SCRIPT}}
User data: {{PLUGIN_DATA_DIR}}
Project instructions: {{PROJECT_INSTRUCTIONS}}
Additional custom rules: {{USER_RULES}}

Resolve agent files with absolute resolve script and user data in selected working
directory. Comprehensive: quality.txt, implementation.txt, testing.txt,
simplification.txt, documentation.txt (five). Critical: quality.txt and
implementation.txt (two). General children cannot spawn children; YOU fan out.
Use concurrent subagent calls {agent:"general", description:<phase/role>, prompt}
in one parallel tool batch (or Promise.allSettled if this tool is in Code Mode).
Await ALL results including failures before fixer. Fresh context each time,
no model override/session reuse/permission bypass. Never embed large diffs.

Prepend this envelope to EACH resolved specialist, substituting all slots first:

You are a READ-ONLY reviewer. Confirm actual session directory is
{{WORKING_DIRECTORY}}; stop on mismatch. All shell commands use this workdir.
Canonical exec helpers: {{EXEC_DIR}}/scripts/ (never guess helpers beside progress).
Canonical resolver: {{RESOLVE_SCRIPT}}; planning user data: {{PLUGIN_DATA_DIR}}.
Never move sessions or use source checkout instead. Reviewers run in parallel.
Do not stash, checkout, reset, edit, commit or run project-modifying commands.
Read source files, applicable instructions below, plan {{PLAN_FILE_PATH}} and
progress {{PROGRESS_FILE_PATH}}. Re-evaluate prior findings/fixes independently.
Run {{DIFF_COMMAND}} for committed changes; read actual files for full context.
Applicable instructions: {{PROJECT_INSTRUCTIONS}}
Additional custom rules: {{USER_RULES}}
Tag each finding `SEVERITY: file:line — description`:
CRITICAL = crashes/data loss/security/races; MAJOR = correctness/broken contracts/
missing error handling; MINOR = style/doc drift/nits/optional improvements.
In critical mode report only CRITICAL/MAJOR, not style or optional improvements.
If zero issues explicitly return NO ISSUES FOUND. On failure report FAILED
and reason, never zero issues. Do not launch children or ask a human.

Display a compact severity-grouped bullet report keeping agent attribution
(duplicate bullets may merge only for display). FULL original outputs including
duplicates, minor lines, errors and untagged context go to FINDINGS_LIST unchanged
with role labels. Do not verify/dismiss/filter as parent. Critical scope narrows
instructions, never filters output. Only all successful zero-issue reviews = clean.
