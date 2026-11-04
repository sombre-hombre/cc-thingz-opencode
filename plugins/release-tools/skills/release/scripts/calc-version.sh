#!/bin/bash
# MIT; semantic version from the nearest reachable v* tag, without implicit fetch.
set -euo pipefail
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
exec python3 "$SCRIPT_DIR/release.py" version "${1:-}"
