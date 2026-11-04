# Provenance and adaptation

Upstream: https://github.com/umputun/cc-thingz

Pinned commit: `f84b93ca0f04a1406bdbb834d8f1ed1946996d1e`.
MIT copyright and license from Umputun are retained unchanged in `LICENSE`.
This public snapshot has its own clean Git history by sombre-hombre. It does not
claim the upstream implementation as original work, nor require a local upstream
tag to exist. Inspect the pinned upstream commit by its public URL when comparing.

## Preserved workflows

The original sixteen skills and supporting scripts/references remain grouped by
plugin. `make` is additionally a skill so brainstorm → make → exec can hand off in
one OpenCode session. Short slash wrappers share the same instructions. The
original `new` skill is named `release`; `pr` retains its ID while reviewing GitLab
MRs/issues. There are seventeen skills, eighteen commands, two planning agents and
one small skill-evaluation plugin.

Planning keeps context gathering, focused questions, approaches, structured plans
and interactive/internal/external review. Exec keeps ordered task agents,
comprehensive review/fixer, smells, external review/fixer, final critical review,
optional finalization, real V2 statistics and verified completion. Fresh children
receive explicit working directory, plan, progress, instructions and settings.

## Deliberate platform adaptations

- Native V2 `skill`, `question`, `subagent`, session-move and plugin APIs replace
  Claude-only tools and environment substitution. No implicit slash invocation.
- `AGENTS.md`, `.opencode/` and explicitly configured instructions replace Claude
  instruction locations. No automatic loading of `AGENTS.local.md` is assumed.
- GitLab/glab replaces GitHub operations in MR/issue and release workflows. Notes,
  discussions, approvals and merge are distinct confirmed operations; no invented
  formal GitHub review equivalent. Hosts/nested namespaces and pagination are
  handled explicitly. GitLab production writes are not part of automated tests.
- Revdiff file handoffs replace editor interception. Native Plan review is an
  explicit `/review-plan` action, not a simulated ExitPlanMode/write hook.
- Empty/discarded results require a separate user choice; approval and edits
  revalidate snapshots, including Git modes and untracked link contents. No link
  target contents are exposed. Unresolved merge diffs are refused explicitly.
- Worktrees use explicit source HEAD plus V2 session move and source-state guards.
  Retry state and completion delegation are durable; malformed/ambiguous supported
  plan syntax fails rather than silently dropping unchecked work.
- Overrides are resolved project → user → bundled, without seeding copies of every
  default. Rules use first nonempty, resource files first existing.
- Codex retains its own user-selected model. External processes are terminated as
  a group on cancellation/timeout; nonzero/empty/failed output is never clean.
- Stats use actual available API evidence, not Claude transcript assumptions.
  Missing usage/time/billing data is unavailable, not zero or invented totals.
- Linux/macOS helpers use Python path resolution, POSIX process checks, atomic
  exclusive rename APIs and platform clipboard tools. No GNU readlink dependency.
- Personal plans/reports, local installation/backup records, session IDs and model
  usage records are deliberately omitted from this public copy and its history.

Archived Claude hook/config files and HTML-commented original skill bodies are
reference material only. They are excluded from the V2 installation manifest.

## Updating upstream

1. Read `upstream.lock`, then inspect changes between that commit and the desired
   public upstream commit in a separate checkout.
2. Transfer relevant changes with the smallest possible adaptation. Preserve
   workflow stages; record new deliberate behavior differences here.
3. Update lock metadata only when the new source and license are verified.
4. Run the package audit, isolated tests, publication audit and Linux/macOS CI.
5. Keep real run artifacts, accounts, author email addresses and credential files
   outside the public tree. Do not import a private development repository's Git
   history to update this clean snapshot.
