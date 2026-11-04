#!/bin/bash
# resolve a file through the three-layer override chain
# usage: resolve-file.sh <relative-path> [data-dir]
# e.g.: resolve-file.sh prompts/task.md /path/to/plugin/data
# e.g.: resolve-file.sh agents/quality.txt /path/to/plugin/data
#
# data-dir: optional explicit user data directory; otherwise use the XDG config root.
#
# checks in order:
#   1. .opencode/exec-plan/<path> (project override, including empty files)
#   2. <data-dir>/<path> (user override)
#   3. bundled default (derived from script location)
#
# outputs the file content to stdout

set -e

path="${1:-}"
if [ -z "$path" ]; then
    echo "error: usage: resolve-file.sh <relative-path> [data-dir]" >&2
    exit 1
fi

case "$path" in
    /*|../*|*/../*|*/..|..)
        echo "error: path must be relative and stay inside the override dir: $path" >&2
        exit 1 ;;
esac
data_dir="${2:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning}"

# derive skill root from script location
# script is at <skill-root>/scripts/resolve-file.sh
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f ".opencode/exec-plan/$path" ]; then
    cat ".opencode/exec-plan/$path"
elif [ -n "$data_dir" ] && [ -f "$data_dir/$path" ]; then
    cat "$data_dir/$path"
elif [ -f "$SKILL_ROOT/references/$path" ]; then
    cat "$SKILL_ROOT/references/$path"
else
    echo "error: file not found in override chain: $path" >&2
    exit 1
fi
