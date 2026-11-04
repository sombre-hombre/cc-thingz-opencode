# V2 review and completion (MAIN SESSION playbook, upstream steps 7–13)

Continue only after task-loop admission says tasks-complete. Do not execute the
inactive migration reference in SKILL.md. Resolve this and ALL prompts/agents via
`bash <EXEC_DIR>/scripts/resolve-file.sh <relative-file> <PLUGIN_DATA_DIR>` in the
selected WORKING_DIRECTORY. Re-read overrides each iteration. Empty/invalid
overrides, missing context, denials and failed children are NOT clean reviews.

Render double-brace slots with task-loop.py render and a JSON context (single-pass,
never shell eval). Carry the full task envelope: absolute working directory, plan,
progress, helpers, default branch, settings, rules/source and applicable AGENTS.md
and explicitly loaded local instructions. Also supply REVIEW_PHASE, DIFF_COMMAND,
FINDINGS_LIST, ROOT_SESSION_ID and STATS_EVIDENCE_PATH as needed. Unknown root ID
or unavailable API must be explicit unavailable, never pick a newest session.
Children confirm actual session directory; stop on mismatch. In worktree mode
verify the source guard after each phase; never use the original checkout instead.

All children: `subagent({agent:"general", description:<phase and role>, prompt:<rendered>})`.
No reused sessionID, model override unless authorized, permission bypass or nested
children. Only review specialists run concurrently; fixers wait for ALL reviewers.
Append phase/iteration/status, FULL outputs and errors with append-progress.sh.
Terminate EVERY stdin block with a newline before the next append, including
stats Markdown: the upstream helper preserves stdin bytes and does not add one.
Store child IDs and actual call timestamps for stats; no file-mtime parallelism.
No code work by the orchestrator.

Prefer inline rendered prompts. For large payloads an explicit absolute rendered
file is allowed ONLY if fully substituted before dispatch, hashed and immutable
until return, and the fresh child actually reads ALL its contents (chunk large
files without skipping/truncating). Include working directory and file path in
the dispatched envelope. Verify the full unfiltered payload reached the child
from actual read/tool evidence; a bare filename or summary is not sufficient.

## 7. Comprehensive, then critical re-check

Loop at most settings.review_iterations (default 5; zero explicitly skipped).
First iteration: resolve/read prompts/review.md as YOUR playbook, comprehensive;
fan out quality, implementation, testing, simplification, documentation (five fresh
children) concurrently. Later iterations: critical, quality + implementation (two
fresh children) concurrently. Announce each phase.

Collect every response verbatim with role attribution. Do not pre-filter,
summarize, dismiss or drop duplicates in FINDINGS_LIST: fixer alone verifies
false positives, including out-of-scope/pre-existing reports. A compact severity
bullet list for the user is separate from the complete payload. All successful
reviewers explicitly zero issues → clean, next phase. Failed/malformed reviewer
→ log failed/incomplete (never clean); forward actual findings and diagnostics
to fixer if present, continue later phases exposing incomplete coverage.

For findings launch one fresh fixer from prompts/fixer.md. Show its FIXES section.
After EVERY fixer (all phases), detect VCS; display every path from
`git status --porcelain` or `hg status` and warn that uncommitted changes are absent
from the committed branch diff. Report-only: do not retry, abort or commit leftovers
because of status. Re-loop phase 1 after fixer even if it rejected all findings.
At limit report max iterations reached, moving on (NOT reviews passed).

## 8. Smells

Once only: resolve agents/smells.txt, prepend review.md's read-only/context/severity
envelope; one fresh reviewer, full findings → fresh fixer if any. Same status/error
reporting. No smells loop, even when review_iterations is zero.

## 9. External adversarial loop

Re-detect VCS. Hg: explicitly skipped git-only (custom hg workflow requires an
explicit adapted override AND authorization). At most external_review_iterations
(default 10; zero skipped). Resolve prompts/codex-review.md; for older overrides
use only content after `## Prompt`, ignore old launcher instructions. Every
iteration reviews committed `git diff DEFAULT_BRANCH...HEAD`; pass plan/progress
and applicable instructions. Write prompt/request JSON using patch, never shell
interpolation. Request fields: command (exact user settings.external_review_cmd),
prompt_file (absolute), cwd (WORKING_DIRECTORY), output_dir (new unique absolute
run/iteration directory under /tmp/opencode), timeout (3600 seconds).

Run `python3 <EXEC_DIR>/scripts/exec-review.py external <request-json>` using shell
background:true if needed; await completion notification, do not poll. Read result
JSON plus separate stdout/stderr files and actual returncode. Helper always calls
run-external-review.sh with exact command as argv[1], prompt as final argv. Never
call Codex directly. Command whitespace-splits only, no shell quoting grammar;
use wrapper for spaces/quotes. Metacharacters remain literal. CODEX_MODEL opt-in,
otherwise inherit Codex config; CODEX_NO_OVERRIDES=1 suppresses ALL -c overrides.

- skipped only exit 127 AND run-external-review: stderr marker; quote exact reason.
  Reviewer's own 127 without marker is failed.
- timeout, other nonzero, whitespace/empty stdout or non-review output = failed;
  report exit/error and continue phase 4. Never scan stderr as findings.
- clean requires NO ISSUES FOUND and no whole-word CRITICAL/MAJOR in stdout.
  Tags case-insensitive whole words. Without marker or any severity tag output is
  failed, not minor. Wrapped/untagged lines alongside a tag remain full findings,
  default minor. Blocking findings win over clean marker.
- findings → full unedited stdout to fresh fixer (description Fixer - external
  review); show FIXES, append results, report status. Minor-only → STOP after fixer;
  blocking → next iteration. At limit max iterations reached, moving on.

Custom command read-only contract is trusted, NOT a sandbox. Codex uses --sandbox
read-only. No reviewer edits/publications; failures never count as review success.
Keep full stdout findings and separate stderr artifact. In progress record stderr
path and concise error diagnostics, NOT the entire stderr transcript: Codex may
echo the prompt and read the whole progress, recursively replaying old decisions
and control-marker examples. Never merge stderr into findings or control state.

## 10. Critical-only

Single pass regardless of review_iterations: quality + implementation in parallel,
critical. Full outputs → fresh fixer if findings. Do not discard MINOR lines from
payload even if reviewer violated critical-only scope. Same errors/status, no loop.

## 11. Optional finalize

Re-detect VCS; Hg skipped git-only, finalize_enabled=false explicitly skipped.
Otherwise one fresh child with prompts/finalizer.md. Best effort; failure does not
block stats/completion. Preserve dirty/unrelated changes. Never push, publish,
automatically stash/reset or rewrite unrelated history. Pass recorded run-owned
commit OIDs and explicit rewrite authorization; absent authorization means verify
without rebase/squash, recording why. No automatic fetch in offline runs.

## 12. Stats

Collect actual root/descendant API evidence through native authenticated CLI:
`python3 <EXEC_DIR>/scripts/exec-review.py stats <ROOT_SESSION_ID>`; save JSON under
run as STATS_EVIDENCE_PATH. Only known root, never caller parent/latest log.
Point-in-time snapshot BEFORE stats child/completion, not final billing. API
failures are unavailable with diagnostics. One fresh read-only child from
prompts/stats.md, progress and VCS evidence; show COMPLETE Markdown verbatim.
Best effort, report failure without blocking.

## 13. Completion (sole move owner)

Re-read the plan and run this completion admission gate before any completed
event or move attempt:

```bash
python3 <EXEC_DIR>/scripts/task-loop.py check-move <absolute-plan> <absolute-progress>
```

Require exit 0 and state `ready`. Only the exact durable, validated delegated
move may remain unchecked (`completion_move_pending: true`); it stays pending
until move-plan.sh verifies the destination. All other unchecked tasks,
missing/malformed plans, corrupt progress or stale/foreign delegation stop
completion. Never replace this gate with an unconditional all-checkboxes check.
Report EVERY timestamped/plain [decision]/[deviation] entry and reason whether
finalize ran or not, under “Decisions made autonomously / Deviations from the plan”;
explicitly none if none. Collector:
`grep -E '^(\[[^]]*\] )?\[(decision|deviation)\]' <progress>`.
Display each collected entry verbatim as its own bullet with reason; do not
replace this full report with a summary or merely a filename. Log any newly
identified transport/control-flow deviation and its reason before collecting.
Append completed plus actual review/finalize outcomes. Call `move-plan.sh PLAN PROGRESS` ONCE from
selected directory AFTER stats (no children move it); scoped commit, no push.
Before call append an exact un-timestamped event line through append-progress.sh
stdin: prefix `[completion-move-attempt] ` followed by JSON with this absolute
plan path and destination. Parse ONLY anchored event lines with valid JSON and
matching plan identity on resume, never substring-search transcripts/instructions
for "move-attempt". If already attempted inspect recorded result/destination,
never automatically reattempt. Append `[completion-move-result] ` JSON with actual
exit/output/destination/commit afterwards. Best-effort error/no-op
is not moved; append result and leave delegated completion pending. The helper
checks a delegated move checkbox only in the verified destination, before committing.
Only print “plan moved to completed/” on actual
`moved plan to ...` output and verified destination/commit. Report all tasks
completed but distinguish clean/skipped/failed/max-iter and finalized/skipped/failed;
never unconditional “reviews passed, branch finalized” on partial coverage.
Report selected worktree path/branch and source guard if isolated.
