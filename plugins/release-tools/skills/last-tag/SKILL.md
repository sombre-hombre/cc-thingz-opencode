---
name: last-tag
description: Show commits since the last tag in a formatted table. Use when user asks "what changed since last release", "commits since last tag", "last-tag", "what's new", or wants to see recent unreleased changes.
---

# Last Tag - Commits Since Last Release

Show commits since the last tag in a formatted table with optional details.

## Activation Triggers

- "last tag", "last-tag", "since last tag"
- "what changed since last release"
- "commits since last tag"
- "what's new", "unreleased changes"

## Workflow

Use V2 `shell`, `read`, `question`. Resolve the skill base with `realpath`; the
canonical sibling `../release/scripts/release.py` is HELPER. For separately copied
skills resolve `<config>/skills/release/scripts/release.py` instead, where config
is `${XDG_CONFIG_HOME:-$HOME/.config}/opencode`. Quote paths, keep an explicit
repository-root workdir. Slash arguments are data, never shell code.

1. Fetch tags from remote and get the last tag:
```bash
git fetch origin --tags
```
Then get the last tag:
```bash
git describe --tags --abbrev=0
```
Stop on fetch/auth/network failure; do not reinterpret it as no tags. In explicit
offline mode disclose local/unrefreshed tags. Store the nearest reachable tag
(all names, not only v*). Validate HEAD/repository separately before deciding no tags.

2. Get commits since that tag with format `date|author|hash|subject` (substitute TAG with actual value):
```bash
python3 HELPER last-tag
```

The helper formats the table using NUL-delimited fields and escapes Markdown
pipes, so pipes in authors/subjects do not shift columns. No tag is a normal result;
broken Git is a failure. Substitute the actual absolute HELPER path.

3. Check if all commits have the same author - extract unique authors from step 2 output.
If only one unique author name appears in all rows, it's a single author.

4. Format output:

**If single author** (count = 1):
```
Last tag: v1.2.3
Author: John Doe

| Date       | Commit  | Description                    |
|------------|---------|--------------------------------|
| 2025-12-20 | abc1234 | fix: resolve null pointer      |
| 2025-12-19 | def5678 | feat: add user authentication  |
```

**If multiple authors** (count > 1):
```
Last tag: v1.2.3

| Date       | Author   | Commit  | Description                    |
|------------|----------|---------|--------------------------------|
| 2025-12-20 | John Doe | abc1234 | fix: resolve null pointer      |
| 2025-12-19 | Jane Doe | def5678 | feat: add user authentication  |
```

**If no tag exists**:
```
No tags found in repository
```

**If no commits since tag**:
```
Last tag: v1.2.3
No commits since this tag
```

## Interactive Details

After displaying a nonempty table, use V2 `question`:

```
question: "Show commit details?"
header: "Details"
options:
  - label: "All commits"
    description: "Show full details for each commit"
  - label: "None"
    description: "Skip details"
  - label: "Specific commit"
    description: "Enter commit hash to inspect"
```

**If "All commits"**: Run once for the entire displayed range:
```bash
python3 HELPER details all
```
The helper includes every commit once: commit hash, author with email, date,
subject, body, and file change stats. Preserve this output; do not invoke it per commit.

**If "None"**: End.

**If "Specific commit"** or user enters hash via "Other": run `python3 HELPER
details HASH` for that displayed hash only. Helper validates hex, resolves the
commit, verifies membership in TAG..HEAD and uses argv plus `--` (no shell eval).
It runs the original `git show --stat` format above for selected commits, including
author email, date, subject/body and file stats. Unknown/out-of-range hashes fail;
do not guess another commit. None ends, no-tags/no-commits need no drill-down.
