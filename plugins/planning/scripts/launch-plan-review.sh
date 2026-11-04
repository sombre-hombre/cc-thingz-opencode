#!/usr/bin/env bash
# V2 port of upstream launch-plan-review.sh (MIT, see LICENSE/upstream.lock).
# Keep the entrypoint relocatable, including a symlink installation.
# Explicit tmux/Kitty overlays or independent Kitty/Foot windows; shared handoff.
set -euo pipefail
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "${BASH_SOURCE[0]}")"
exec python3 "$SCRIPT_DIR/plan-review-launcher.py" "$@"
