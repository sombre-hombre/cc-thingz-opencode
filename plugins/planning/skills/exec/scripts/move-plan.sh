#!/bin/bash
# move a completed plan file into its sibling completed/ directory and commit it
# usage: move-plan.sh <plan-file-path> [progress-file]
# no-op if the plan is already under completed/ or the file is missing
# VCS-aware commit via stage-and-commit.sh; does NOT push

set -e

if [ $# -lt 1 ]; then
    echo "error: usage: move-plan.sh <plan-file-path>" >&2
    exit 1
fi

plan="$1"
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}")"

# already under completed/ — nothing to do
case "$plan" in
*/completed/*)
    echo "plan already under completed/: $plan"
    exit 0
    ;;
esac

# file missing (already moved, or never existed) — nothing to do
if [ ! -f "$plan" ]; then
    echo "plan file not found, skipping move: $plan" >&2
    exit 0
fi

base="$(basename "$plan")"
dest_dir="$(dirname "$plan")/completed"
dest="$dest_dir/$base"

# refuse to clobber an existing completed plan with the same name
if [ -e "$dest" ]; then
    echo "error: destination already exists, refusing to overwrite: $dest" >&2
    exit 1
fi

if [ -n "${2:-}" ]; then
    python3 "$SCRIPT_DIR/task-loop.py" check-move "$plan" "$2"
fi

mkdir -p "$dest_dir"
# An untracked plan has no old VCS path to stage after the filesystem move.
# Keep tracked removal + destination together, but never broaden the selection.
vcs=$(bash "$SCRIPT_DIR/detect-vcs.sh")
tracked=false
case "$vcs" in
git)
    if git ls-files --error-unmatch -- ":(literal)$plan" >/dev/null 2>&1; then tracked=true; fi
    ;;
hg)
    if [ -n "$(hg files -- "$plan" 2>/dev/null)" ]; then tracked=true; fi
    ;;
*) echo "error: unsupported VCS: $vcs" >&2; exit 1 ;;
esac
mv "$plan" "$dest"
if [ -n "${2:-}" ]; then
    python3 "$SCRIPT_DIR/task-loop.py" complete-move "$plan" "$2" "$dest"
fi

# stage-and-commit.sh stages both the (now-removed) old path and the new path;
# git and hg each record this as the rename plus commit
if "$tracked"; then
    bash "$SCRIPT_DIR/stage-and-commit.sh" "docs: move completed plan $base to completed/" "$plan" "$dest"
else
    bash "$SCRIPT_DIR/stage-and-commit.sh" "docs: move completed plan $base to completed/" "$dest"
fi

echo "moved plan to $dest"
