#!/bin/bash
# MIT; upstream release contracts, now GitLab-only + real glab loopback fixtures.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/test-release-tools.py"
