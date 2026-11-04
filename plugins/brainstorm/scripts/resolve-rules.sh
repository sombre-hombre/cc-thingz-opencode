#!/bin/bash
# resolve custom rules file through the two-layer override chain
# usage: resolve-rules.sh <filename> [data-dir]
# e.g.: resolve-rules.sh brainstorm-rules.md /path/to/plugin/data
#
# data-dir: optional explicit user data directory; otherwise use the XDG config root.
#
# checks in order (first-found-wins, not merged):
#   1. .opencode/<filename> (project override)
#   2. <data-dir>/<filename> (user override)
#
# outputs file content to stdout if found, empty output if not
# missing/empty rules exit 0; read errors propagate

filename="${1:-}"
if [ -z "$filename" ]; then
    exit 0
fi

data_dir="${2:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/brainstorm}"

if [ -f ".opencode/$filename" ] && [ -s ".opencode/$filename" ]; then
    cat ".opencode/$filename"
    exit $?
elif [ -n "$data_dir" ] && [ -f "$data_dir/$filename" ] && [ -s "$data_dir/$filename" ]; then
    cat "$data_dir/$filename"
    exit $?
fi

exit 0
