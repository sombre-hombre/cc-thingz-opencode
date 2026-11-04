#!/bin/bash
# Port of upstream first-nonempty rules scenarios, plus XDG and linked entrypoints.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash "$ROOT/tests/resolver-rules-cases.sh" planning
