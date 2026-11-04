#!/usr/bin/env bash
# The Claude hook is provenance, not the active V2 route.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$(mktemp -d /tmp/opencode/plan-disable-test.XXXXXX)"
trap 'rm -rf "$RUN"' EXIT
PLANNING_DISABLE_REVDIFF=0 bash "$ROOT/plugins/planning/scripts/launch-plan-review.sh" \
    "$RUN/missing-plan" --output "$RUN/annotations" --status "$RUN/status" > "$RUN/stdout"
python3 - "$RUN" <<'PY'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
assert json.loads((p / 'status').read_text())['state'] == 'skipped'
assert not (p / 'annotations').read_bytes()
assert not (p / 'stdout').read_bytes()
print('PASS: explicit skipped status, nonempty value 0, no UI/annotations/approval')
PY
