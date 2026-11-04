# cc-thingz for OpenCode V2

An OpenCode V2 adaptation of [umputun/cc-thingz](https://github.com/umputun/cc-thingz),
with GitLab workflows, interactive revdiff reviews, and reusable planning tools.

**17 skills · 18 slash commands · 2 review agents · 1 skill-evaluation plugin**

Maintained by **sombre-hombre**. MIT; upstream copyright and license are preserved.
The original source is pinned in [upstream.lock](upstream.lock).
This public repository starts with a clean history; local installation records,
model transcripts, personal paths and development-session reports are excluded.

## Platforms and requirements

Targets **Linux and macOS**. Windows is not supported.

| Component | Requirement |
|---|---|
| OpenCode | V2; API/SDK integration targets 2.1.1 |
| Python | 3.10+ on PATH as `python3` |
| Shell / VCS | Bash 3.2+, Git 2.28+ |
| Plugin dependency install | Node.js 22.18+ or 24 LTS, npm |
| Interactive review | [revdiff](https://github.com/umputun/revdiff) 1.13+ and Kitty or tmux |
| GitLab review/releases | Authenticated `glab`, including self-hosted GitLab |
| External review | Authenticated Codex CLI, or a configured read-only reviewer |
| Clipboard | macOS: `pbcopy`; Linux: `wl-copy`, `xclip` or `xsel` |
| ask-codex timeout | GNU `timeout` or `gtimeout` (`brew install coreutils` on macOS) |

Kitty independent windows and explicitly targeted Kitty overlays work with native
macOS GUI sessions and Linux displays. Foot requires Linux/Wayland. Tmux requires
an explicitly selected socket, client and pane, never a guessed active client.
No desktop configuration or remote-control setting is changed automatically.

See [portability and verification](docs/portability.md) for exact boundaries.
The macOS CI job must run on a real macOS runner before a native pass can be claimed.
Mocking Darwin on Linux does **not** establish native macOS compatibility.

## Install

Clone this repository into a stable location and run from its root:

```sh
mkdir -p /tmp/opencode
npm --prefix integrations/opencode/skill-eval ci --ignore-scripts --no-audit --no-fund
python3 scripts/install.py inventory > /tmp/opencode/cc-thingz-inventory.json
```

Read the inventory before replacing an existing installation. Back up any custom
skills or overrides you want to keep. The installer replaces only recognized
legacy entries whose exact reviewed fingerprints still match:

```sh
python3 scripts/install.py install --replace-inventory /tmp/opencode/cc-thingz-inventory.json
```

For an empty target, `python3 scripts/install.py install` is sufficient.
The installer performs no network requests, npm install, login, model calls or UI
launch. It prints the state manifest and backup location: **keep those paths**.

- Configuration: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode` on both platforms.
- State/backup: `${XDG_STATE_HOME:-$HOME/.local/state}/cc-thingz/<target-hash>/`.
- `--target-root PATH` and `--state-dir PATH` support isolated installations.
- Default mode registers symlinks. Do not move/delete the checkout afterwards.
- `--mode copy` snapshots the resource tree into state, then registers that
  snapshot with symlinks. It is not a symlink-free fallback.
- Repeating the same installation returns `unchanged`; it does not refresh a copy.
- Existing project/explicit skill definitions can override global IDs in OpenCode.

To undo an installation, use its own printed state directory, not an example:

```sh
python3 scripts/install.py restore --state-dir "/absolute/path/to/the/printed/state-directory"
```

Restore checks backup and owned-entry fingerprints, retains unrelated files, and
refuses to overwrite foreign edits. Its journal supports recovery after interrupted
file transitions. Atomic no-replace operations use Linux `renameat2` or macOS
`renamex_np`; an unsupported platform fails rather than falling back to overwriting.
Snapshot-only user data is not rolled back over subsequent edits.

## Skills and commands

Use `@skill-id` in the composer or `/skill-id arguments`. Slash commands are thin
wrappers: they load the skill only when not already available and preserve argument
text as data. They do not execute arguments as shell commands.

| ID | Purpose |
|---|---|
| `brainstorm` | Clarify an idea, compare approaches, validate a design |
| `make` | Write an implementation plan and arrange review |
| `exec` | Sequential task agents, isolated worktree, reviews and completion |
| `pr` | GitLab MR/issue review; original ID retained |
| `git-review` | Annotate a Git diff in revdiff |
| `writing-style` | Direct technical comments and commit messages |
| `release` | Version, notes/changelog preview and confirmed GitLab release |
| `last-tag` | Commits since the latest tag and optional details |
| `ask-codex` | Independent read-only Codex investigation/review |
| `dialectic` | Two opposing parallel analyses with verified evidence |
| `root-cause-investigator` | Evidence-based 5-Why investigation |
| `learn` | Save selected knowledge in applicable project instructions |
| `clarify` | Investigate confusion before proposing a fix |
| `wrong` | Re-evaluate an unsuccessful approach |
| `md-copy` / `txt-copy` | Prepare and copy exact Markdown/plain text |
| `backlog` | Verified deferred-work items in `docs/backlog/` |

The additional command `/review-plan /absolute/path/plan.md` uses the same `make`
skill in review-only mode. The agents are `plan-review` and `external-plan-review`.
The small plugin reminds the model to evaluate relevant skills on a new user
request; it does not execute skills, spawn agents or make model requests itself.

### Planning and execution

```text
/brainstorm Design a configuration validator
# After agreeing on the design, choose make without repeating answered questions.
/make Implement the agreed validator
# After plan approval, explicitly choose execution:
/exec "/absolute/project/docs/plans/config validator.md"
```

Handoffs preserve context in the current session. Exec passes explicit paths,
instructions and task details to each fresh agent. Tasks run sequentially; review
specialists can run in parallel. Worktrees start at the selected source HEAD.
Review/fix, external review, final critical review, optional finalize and statistics
precede one verified move into `completed/`. Rewrite, fetch, squash and push require
separate authorization. Failed checks are not marked passed.

### Revdiff without tmux

```text
/review-plan "/absolute/project/docs/plans/feature.md" --terminal kitty-window
/git-review --staged --terminal kitty-window
```

Other choices: `foot-window` (Linux/Wayland), `kitty-overlay --kitty-socket ADDRESS
--kitty-window-id ID`, or `tmux --tmux-socket PATH --tmux-client CLIENT --tmux-pane %N`.
The selected terminal must already be installed; the helper does not enable remote
control or change its configuration. Runtime scratch files use unique directories
under the generic `/tmp/opencode` scratch root; create that root after system cleanup.

After a review, `annotations` means read and apply the requested changes against
the verified snapshot, then reopen. `needs-confirmation` means ask **Review complete /
Open again / Leave unfinished**. A blank result or discarded annotation is not
approval. The snapshot is revalidated after the answer. `failed`, `cancelled` and
`stale` never mean clean; explicit disabling (`PLANNING_DISABLE_REVDIFF` set to any
nonempty value) returns `skipped`. Git-review rejects unresolved merges explicitly.

Direct helper example, only after agreeing to open a window:

```sh
run=$(mktemp -d /tmp/opencode/plan-review.XXXXXX)
bash plugins/planning/scripts/launch-plan-review.sh "/absolute/path/plan.md" \
  --terminal kitty-window --output "$run/annotations.md" --status "$run/status.json" \
  --exit-code-on-annotations
```

The launcher returns zero on a successful handoff; the internal revdiff code
(`10` for annotations with the flag) is in `status.json.revdiff_exit`.
Output/status files must not exist before launch. Source coordinates are bound to
the reviewed bytes and Git modes; stale snapshots must be reviewed again.

Native OpenCode Plan has no Claude ExitPlanMode hook. Save its plan and explicitly
invoke `/review-plan`; writing a file does not imply approval or open a terminal.

## Configuration

Optional file: `<OpenCode config>/data/cc-thingz/planning/settings.json`:

```json
{
  "external_review_cmd": "",
  "task_retries": 1,
  "review_iterations": 5,
  "external_review_iterations": 10,
  "finalize_enabled": true,
  "plans_dir": "docs/plans"
}
```

An empty external command uses Codex. Custom commands receive the prompt as their
last argument, run read-only, consume no stdin, and return severity-tagged findings
or a standalone `NO ISSUES FOUND` line. Missing tools, failures and empty output are
distinct states. Counters are integers ≥0; plans_dir is a safe project-relative path.

- Rules: first **nonempty** `.opencode/planning-rules.md` or `brainstorm-rules.md`,
  then the matching file in user data `cc-thingz/planning/` or `brainstorm/`.
- Exec overrides: first existing `.opencode/exec-plan/{prompts,agents}/...`, then
  user data `cc-thingz/planning/{prompts,agents}/...`, then bundled defaults.
  An empty file override intentionally shadows the default; no automatic seeding.
- `customize-file.sh RELATIVE_PATH [--user]` copies only the requested default.
- Project guidance uses scoped `AGENTS.md` and explicitly configured instructions.
  `AGENTS.local.md` is not automatically loaded.
- Agents inherit the current model. External Codex uses its own configuration;
  `CODEX_MODEL` optionally overrides it. `CODEX_NO_OVERRIDES=1` disables the helper's
  `-c` overrides. No credentials or configuration are copied.
- Clipboard copying changes the current clipboard only when requested. Tests use
  fixtures and never read or overwrite the user's selection.

## Tests and publication checks

Install Mercurial, glab, zsh and GNU coreutils for the complete test suite, in addition to
the runtime prerequisites. GitLab/release fixtures exercise the real CLI against a
local HTTP server; authentication is not needed. CI installs glab 1.124.0 from the
official release with checksum verification on both Linux and macOS.
With the pinned npm dependencies installed:

```sh
python3 tests/check-port.py
bash tests/run.sh
python3 scripts/check-public.py
```

Tests isolate HOME/XDG/Git/Hg and use synthetic data. They do not require model
credentials, real GitLab writes, UI windows or a real clipboard. Missing dependencies
fail clearly instead of being counted as passes. Optional live scripts in
`tests/smoke/` are not part of the regular suite; review them and their explicit
authorization flags before running. Keep their output outside this repository.

Linux/macOS jobs are defined in `.github/workflows/test.yml`. A workflow definition
is not evidence of a completed run. The offline publication audit checks common
secrets, user-home paths, real session IDs and reachable Git history; no heuristic
scanner can guarantee that arbitrary secrets are absent.

## Attribution and updates

See [docs/porting.md](docs/porting.md) for retained workflows, deliberate adaptations
and updating the pinned source. This is not an upstream Claude plugin marketplace
installation: `plugins/` groups sources; the installer registers only V2 entries
from [install-manifest.json](install-manifest.json). Archived Claude hooks/metadata
are retained for reference and never auto-loaded.
