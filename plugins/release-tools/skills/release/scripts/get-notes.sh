#!/bin/bash
# MIT; preserve explicit platform admission, never silently degrade API failures.
set -euo pipefail
if [ "${1:-}" != gitlab ]; then
    echo "error: platform required: gitlab (only supported target)" >&2
    exit 1
fi
shift
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
exec python3 "$SCRIPT_DIR/release.py" notes "$@"
