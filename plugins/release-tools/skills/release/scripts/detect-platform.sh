#!/bin/bash
# MIT; GitLab-only target validation, including nested/self-hosted origins.
set -euo pipefail
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
exec python3 "$SCRIPT_DIR/release.py" detect "$@"
