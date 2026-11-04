# External review prompt

This is the prompt sent to the external review tool. Render every double-brace
slot before passing, including absolute selected directory/plan/progress.

Every iteration uses `DIFF_COMMAND` = `git diff DEFAULT_BRANCH...HEAD` because fixers commit their changes before the next review.

The active review-phases.md Step 9 controls invocation and exit handling. A 127
is skipped only with the helper's stderr marker. Render all double-brace slots.

## Prompt

READ-ONLY review in {{WORKING_DIRECTORY}}. Do not edit/stash/reset/checkout/commit,
publish or run mutating project commands. Run {{DIFF_COMMAND}} to see committed
changes (every iteration includes committed fixer changes). Read actual source
and plan {{PLAN_FILE_PATH}} for intent, progress {{PROGRESS_FILE_PATH}} for previous
fixes; independently re-evaluate them. Check bugs/security/races/error handling/
quality. Applicable AGENTS.md and explicitly loaded instructions:
{{PROJECT_INSTRUCTIONS}}
Additional custom rules: {{USER_RULES}}

Tag each finding with severity:
- CRITICAL: bugs causing crashes, data loss, security holes, race conditions
- MAJOR: real correctness issues — incorrect behavior, missing error handling, broken contracts
- MINOR: style, documentation drift, doc/code inconsistencies, nits, optional improvements

Format each finding on its own line as: `SEVERITY: file:line - description`.

If nothing found: NO ISSUES FOUND.
