#!/usr/bin/env bash
# Run imported upstream tests without inheriting user configuration or CODEX_*.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -c 'import sys; sys.exit("Python 3.10+ is required" if sys.version_info < (3, 10) else 0)'
SDK="${SKILL_EVAL_SDK:-$ROOT/integrations/opencode/skill-eval}"
mkdir -p /tmp/opencode
RUN="$(mktemp -d /tmp/opencode/cc-thingz-tests.XXXXXX)"
mkdir -p "$RUN"/{source,home,config,data,state,cache,tmp,logs}
cp -a "$ROOT/plugins" "$ROOT/scripts" "$ROOT/tests" "$ROOT/commands" "$ROOT/integrations" \
    "$ROOT/install-manifest.json" "$ROOT/upstream.lock" "$ROOT/LICENSE" "$RUN/source/"
printf 'Isolated test run: %s\n' "$RUN"

failed=0
for dependency in bash git python3 hg glab zsh node; do
    if ! command -v "$dependency" > /dev/null 2>&1; then
        printf 'MISSING dependency: %s (coverage incomplete)\n' "$dependency"
        failed=$((failed + 1))
    fi
done

run_test() {
    local name="$1" rc=0
    shift
    if (
        cd "$RUN/source"
        env -i PATH="$PATH" HOME="$RUN/home" TMPDIR="$RUN/tmp" \
            XDG_CONFIG_HOME="$RUN/config" XDG_DATA_HOME="$RUN/data" \
            XDG_STATE_HOME="$RUN/state" XDG_CACHE_HOME="$RUN/cache" \
            SKILL_EVAL_SDK="$SDK" \
            GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
            HGRCPATH=/dev/null LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
            "$@"
    ) > "$RUN/logs/$name.log" 2>&1; then
        printf 'PASS %s\n' "$name"
    else
        rc=$?
        failed=$((failed + 1))
        printf 'FAIL %s (exit %s)\n' "$name" "$rc"
        tail -n 30 "$RUN/logs/$name.log"
    fi
}

shopt -s nullglob
suites=("$RUN/source/tests"/test-*.sh)
if (( ${#suites[@]} == 0 )); then
    printf 'FAIL: no shell suites found\n'
    failed=$((failed + 1))
fi
for suite in "${suites[@]}"; do
    run_test "$(basename "$suite" .sh)" bash "$suite"
done
run_test plan-annotate-self-test python3 plugins/planning/scripts/plan-annotate.py --test
run_test git-review-self-test python3 plugins/review/skills/git-review/scripts/git-review.py --test

printf 'Failure/dependency count: %s; logs: %s/logs\n' "$failed" "$RUN"
(( failed == 0 ))
