# V2 stats (fresh READ-ONLY general child)

Working directory: {{WORKING_DIRECTORY}}
Canonical exec helpers: {{EXEC_DIR}}/scripts/
Root session ID: {{ROOT_SESSION_ID}}
API evidence JSON: {{STATS_EVIDENCE_PATH}}
Progress: {{PROGRESS_FILE_PATH}}
Default branch: {{DEFAULT_BRANCH}}

Confirm actual directory. Read only evidence/progress and VCS state here; never
edit/commit/move files, launch children or ask questions. Evidence comes from
exec-review.py stats using actual V2 Session.Info root/descendants and context tool
timestamps. No Claude JSONL/latest-session guessing/fabricated tokens or durations.
Snapshot precedes this child/completion. Unavailable metrics say unavailable plus
reason; missing is not zero. Tools in API evidence cover visible context only:
label counts with that scope, do not claim complete historical totals after
compaction. Missing phase attribution/intervals are unavailable, not sequential.

Report separate input/output/reasoning/cache.read/cache.write dimensions; do not
add reasoning to output as if disjoint or claim billed tokens from sums. Actual
reported USD only. Count each session once (no reused/forked sessions). Lifespan
updated-created is not active model time. Installed V2 time/tool timestamps are
epoch milliseconds; divide interval differences by 1000 for seconds. Missing
interval endpoints are unavailable. Parallel mode requires actual overlapping
subagent call intervals, never file/session mtimes. Join child_session_id metadata
to actual session IDs for phase descriptions; do not guess from session title.
Missing attribution/metadata is explicitly unavailable.

Read progress for phase outcomes/iterations and EVERY decision/deviation.
Git: diff --shortstat/--stat {{DEFAULT_BRANCH}}...HEAD, log {{DEFAULT_BRANCH}}..HEAD.
Hg: diff --stat -r ancestor(., {{DEFAULT_BRANCH}}), log valid revset, not Git HEAD.
Command errors = unavailable. Foreign staged paths are not delivered changes.

Return ONLY compact Markdown, shown VERBATIM to user:
## Run summary
Snapshot time/root/coverage, token dimensions, cost, agents/tool uses, wall interval
with availability/limitations.
### Per-phase
Table phase | agents | usage | wall | parallel/sequential/unavailable.
### Branch changes
Files/+/-/commit count and top five churn files versus actual default branch.
### Notable
External outcome/early exit, fixer counts, actual review/finalize state, blockers.
Completion/move pending at snapshot. Never turn skipped/failed/max-iter into passed.
