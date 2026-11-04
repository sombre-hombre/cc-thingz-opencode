# Platform support and verification

## Supported design

Linux and macOS are the target platforms; Python 3.10+, Bash 3.2+, Git 2.28+
and Node 22.18+/24 LTS are prerequisites. Both platforms intentionally use the
OpenCode XDG-style config directory, not a guessed macOS Application Support path.

| Boundary | Linux | macOS |
|---|---|---|
| Atomic no-replace installer transition | `renameat2(RENAME_NOREPLACE)` | `renamex_np(RENAME_EXCL)` |
| Symlink-aware script location | Python `os.path.realpath` | Same |
| Worker liveness/zombie detection | POSIX `kill(0)` and `ps` | Same; no `/proc` dependency |
| Independent review window | Kitty; Foot on Wayland | Native Kitty; no DISPLAY needed |
| Explicit overlay/popup | Kitty remote control or tmux target | Same, when configured by user |
| Clipboard | wl-copy, xclip, xsel | pbcopy |
| ask-codex timeout | GNU timeout | GNU gtimeout from coreutils |

The installer has no unsafe rename fallback. An unsupported atomic API returns an
error instead of overwriting an arriving file. Restore retains a journal and
checks ownership/backup fingerprints. This does not protect against an attacker
who controls the installation directories or privileged filesystem tampering.

`/tmp/opencode` is a generic cross-platform scratch root, not a user's installation
path. Create it before running interactive/exec workflows. macOS resolves `/tmp`
to `/private/tmp`; the external-plan review agent allows both canonical locations.
Unique run directories are created by mktemp/tempfile and are not publication files.

## Verification boundaries

- The regular suite passed on Linux during public-copy preparation: 24 shell
  suites and two self-tests, including isolated install/restore and new portability
  and publication regressions. Native macOS results remain unverified until CI runs.
- Regular tests use real local Git/filesystem/process operations and synthetic
  terminal, clipboard, Codex and GitLab fixtures; they do not publish or log in.
- Darwin contract fixtures validate API selection/flags/error handling and native
  Kitty dispatch policy from a Linux host. They are not actual macOS acceptance.
- A Linux/macOS GitHub Actions matrix is provided. Its presence alone is **not** a
  statement that either remote job has already passed.
- Real terminal interaction, clipboard contents, authenticated GitLab operations
  and model workflows need explicit manual/opt-in checks on the target system.
- Optional `tests/smoke/` tools can create real sessions and model requests after
  authorization. They are diagnostic tools, not guaranteed cross-platform CI.
- Common-secret and personal-path scanning is heuristic. Inspect exported files
  and Git metadata before publication; supplement with a dedicated secret scanner.

No personal development-session evidence or local-machine verification reports
are shipped. Run results for this clean public copy should be obtained from its
own tests and CI, not inferred from a private ancestor's historical reports.
