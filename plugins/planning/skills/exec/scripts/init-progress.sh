#!/bin/bash
# initialize the progress file with a header
# usage: init-progress.sh <progress-file> <plan-path> <branch-name>

set -e

file="$1"
plan="$2"
branch="$3"

if [ -z "$file" ] || [ -z "$plan" ] || [ -z "$branch" ]; then
    echo "error: usage: init-progress.sh <progress-file> <plan-path> <branch-name>" >&2
    exit 1
fi

# Resume without truncating durable attempts or decisions. Refuse a mismatched run.
if [ -e "$file" ]; then
    if grep -qxF "Plan: $plan" "$file" && grep -qxF "Branch: $branch" "$file"; then
        echo "$file"
        exit 0
    fi
    echo "error: existing progress belongs to another run: $file" >&2
    exit 1
fi

( set -o noclobber; cat > "$file" <<EOF
# progress
Plan: $plan
Branch: $branch
Started: $(date '+%Y-%m-%d %H:%M:%S')
---
EOF
)

echo "$file"
