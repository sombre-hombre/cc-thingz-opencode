---
name: release
description: Use when user asks to create a release, cut a release, or publish a version. Validates GitLab target, calculates semantic version, generates release notes from merged MRs and commits, shows preview for explicit confirmation before publishing.
---

# Release Workflow

GitLab-only port of upstream `new` (MIT; pinned in upstream.lock). Preserve the
release type → target → prerequisites → version → notes → changelog → preview →
confirmation → publication → result sequence. No GitHub/Gitea fallback.

## Activation Triggers

- "create release", "cut release", "new release"
- "publish version", "bump version", "new version"
- "tag and release"

## Scripts and V2 tools

Use `shell`, `read`, `patch`, `question`; load writing-style with
`skill({"id":"writing-style"})` when editing technical text. Slash wrapper arguments
are user data in the current session, never shell code. Respect preview-only intent.
Resolve the base directory supplied by the skill tool with `realpath` first; retain
the absolute canonical `scripts/release.py` path as HELPER. Quote all paths and use
explicit shell workdir = repository root, including after session moves. Do not use
literal HELPER/TYPE/PREVIEW placeholders in executed commands.

Helpers use Python stdlib, Git, glab 1.124.0. `detect-platform.sh`,
`calc-version.sh TYPE`, `get-notes.sh gitlab` remain Bash entrypoints. Shared
read-only glab transport is Task 10's `pr/scripts/gitlab-context.py`: resolved from
the canonical source tree, or installed `<config>/skills/pr/scripts/` for copies.
The package includes both skills. Missing dependency, auth, fetch, API, parse or
later-page failure aborts with stderr and **no notes/preview stdout**. Never turn
these into "no MRs" or success, and never suppress failures with `|| true`.

## Step 1: Ask Release Type

If not already explicit, use `question` (header Version, single choice):
Hotfix (1.2.3 → 1.2.4), Minor (1.2.3 → 1.3.0), Major (1.2.3 → 2.0.0).
Map to `hotfix`, `minor`, `major`. Cancel stops; do not guess a type.

## Step 2: Detect GitLab Target

Run `bash <canonical-base>/scripts/detect-platform.sh`. It validates origin's
explicit hostname, entire nested namespace and numeric project identity via
`glab api --hostname HOST --method GET projects/ENCODED_PATH`. The full path is
encoded exactly once, not split into owner/repo. SSH/scp/HTTPS and self-hosted
GitLab work; local paths/unknown forges/auth errors stop, not fallback to gitlab.com.
Existing glab host/API mapping is honored; do not change user auth/config.
Show resolved host/project and confirm ambiguity/multiple remotes with the user.
Publication always targets this origin, not an unrelated default glab repository.

## Step 3: Validate Prerequisites

Require a valid non-empty Git repository and clean index/worktree (including
untracked). Ask user to commit/stash themselves; do not discard their work.
Explicitly run `git fetch origin --tags` once, only when network access is allowed.
Failure stops. Helpers never fetch behind the caller's back. For an explicitly
offline fixture preview, label tags as local/unrefreshed; never publish from it.
Check origin push URLs too: if multiple or different from the validated project,
stop and ask; never push a tag to an unreviewed destination.

## Steps 4–5: Current and New Version

Run `git describe --tags --abbrev=0 --match 'v*'` after verifying the repository;
no reachable v* tags means first-release defaults, not a failed repository.
Run `bash <base>/scripts/calc-version.sh TYPE`:

- major → next X.0.0; minor → X.nextY.0; hotfix → X.Y.nextZ.
- First release: v1.0.0 / v0.1.0 / v0.0.1 respectively.
- Strip valid prerelease suffix before bump; invalid version is an error.
- New tag already exists locally or remotely: abort, do not move/delete it.

## Step 6: Generate Notes

Run `bash <base>/scripts/get-notes.sh gitlab`. It collects **all pages** of project
MRs (`state=merged&scope=all&per_page=100`, glab API --paginate --output ndjson).
Keep only `merged_at` strictly after the last reachable v* tag's **creator time**:
tagger date for annotated tags, committer date for lightweight tags, timezone-aware.
Do not filter by creation/update time or author date. No previous tag → all merged
MRs. This preserves upstream's time-based MR contract (not a claim of ancestry on
the current branch); flag unrelated target-branch MRs for user review, not silently
invent a narrower range.

Also collect non-merge commits from `TAG..HEAD`; without a tag only the latest 20.
No MRs legitimately found → commits remain. An API error is NOT this fallback.
Group New Features (feat), Improvements (refactor/perf/chore/docs/style/build/ci/test),
Bug Fixes (fix), Other; strip conventional prefix/scope. Format:

```text
**New Features**
- add user authentication !45 @username
- implement caching d41d3ad

**Bug Fixes**
- resolve login timeout !46 @contributor
```

Compare descriptions after stripping prefix; deduplicate, prefer MR IID/author
over duplicate commit. Helper does exact-description dedup; review semantic
duplicates before presenting. Validate missing/null MR fields as errors, not "null"
entries or silently dropped MRs. Empty notes require investigation/user revision.

## Step 7: Check and Update CHANGELOG

Detect the first exact existing filename: `CHANGELOG.md`, `changelog.md`, `CHANGELOG`.
Read its format (Keep a Changelog, simple list, date-based); propose new section
after header/intro, use generated notes and preserve style. Unknown format → ask
or propose simple `## vX.Y.Z`; no file → skip, do not create unsolicited changelog.
Use the **detected filename**, never hardcode CHANGELOG.md.

Show the planned diff; get permission before changing/committing local files.
Preview-only requests stop with the proposed changelog, no commit. Otherwise use
`patch`, read back, commit only that explicit path with message
`docs: update changelog for vX.Y.Z`. Preserve unrelated staged work; never `git add .`.
Changelog commit changes HEAD: regenerate final preview after it; do not publish
an old snapshot. Explain if cancellation leaves an already agreed local commit.

## Step 8: Preview and Confirm

Run `python3 HELPER preview TYPE`, save stdout only on success to a unique file
under `/tmp/opencode/` (outside the repo), stderr separately. This read-only helper
does not modify changelog, tag, push or publish. It returns head, origin, host,
project ID/path, last tag, version, title, notes, exact changelog filename.
Incorporate agreed editorial notes **into the preview file**, read back, show all
notes and changelog diff, current/new version, `Version X.Y.Z`, target and HEAD.
If no changelog, say none found; distinguish already committed vs proposed update.

Use `question` (header Release) with **Yes, publish** (create annotated tag, push
only tag and publish these exact notes) / **Cancel**. Wait for an explicit answer
after the FINAL preview. Original intent to release, preview exit 0, earlier
changelog approval or silence is not this consent. Preview edit/HEAD/target change
requires fresh preview and fresh confirmation. Cancel → no tag/push/release.

## Step 9: Guarded Publication — ONLY after confirmation

Require an explicitly approved project and write authorization. Recheck clean
state, same HEAD/origin/project, no conflicting local/remote tag; API/auth failure
does not prove absence. Check remote tags with successful `git ls-remote --tags
origin refs/tags/vX.Y.Z refs/tags/vX.Y.Z^{}`; any existing tag stops a NEW release.
No force, branch push, default-branch policy change, credential/config edits.

Create annotated tag at the exact confirmed HEAD, then push only that tag:

```sh
git tag -a "$new_version" "$confirmed_head" -m "Version ${new_version#v}"
git push origin "refs/tags/$new_version:refs/tags/$new_version"
```

Each failure stops before the next action. Do not recreate/delete/move the tag.
Helper publication checks local annotated tag and remote API tag commit/message,
same clean HEAD, canonical directory and target. Compute SHA-256 of final preview
bytes and call `python3 HELPER publish PREVIEW --confirm VERSION@SHA256` only
because the user just confirmed this exact preview (the digest is a staleness
guard, NOT a substitute for consent). It executes installed glab's verified argv:

```sh
glab release create "$new_version" --repo "$full_gitlab_url" \
  --name "Version ${new_version#v}" --notes "$notes" --ref "$confirmed_head" \
  --no-update --no-close-milestone
```

`--ref` prevents a race from tagging default-branch HEAD; `--no-update` prevents
glab's default update-existing-release behavior. No assets/milestones/CI catalog
publication is implied. Read back release via API and verify tag/name/description/
commit before reporting success. A failed/ambiguous response may have published:
inspect remote first, never blindly repeat. If tag pushed but release failed,
report partial state; after resolution/renewed consent retry **only** release
publication with the preserved preview, not tag creation/push. Existing release
is never overwritten. Readback error is not an empty success.

## Step 10: Report Result

Show version and verified `_links.self` URL, changelog commit if any, and whether
publication actually completed. Distinguish local tag / pushed tag / release /
verified readback on every failure. Never claim a fixture preview is a live release.
