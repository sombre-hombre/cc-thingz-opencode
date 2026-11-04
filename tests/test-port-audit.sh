#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/tests/check-port.py" "$ROOT"
python3 "$ROOT/tests/test-port-audit.py"
python3 "$ROOT/tests/test-port-runtime.py"
