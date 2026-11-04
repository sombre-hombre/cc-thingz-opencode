#!/usr/bin/env bash
set -euo pipefail
sdk="${SKILL_EVAL_SDK:-$(pwd)/integrations/opencode/skill-eval}"
test -f "$sdk/node_modules/@opencode/plugin/package.json" || {
    echo "Missing pinned skill-eval SDK: npm install --prefix $sdk --ignore-scripts @opencode/plugin@2.1.1 typescript@5.9.3 @types/node@25.0.0" >&2
    exit 1
}
test "$(node -p "require('$sdk/node_modules/@opencode/plugin/package.json').version")" = 2.1.1
run="$(mktemp -d /tmp/opencode/cc-thingz-skill-eval-unit.XXXXXX)"
trap 'rm -f "$run/node_modules"' EXIT
cp -a integrations "$run/"
mkdir "$run/tests"
cp tests/skill-eval.test.ts "$run/tests/"
ln -s "$sdk/node_modules" "$run/node_modules"
node "$sdk/node_modules/typescript/bin/tsc" --noEmit --strict --skipLibCheck \
    --typeRoots "$sdk/node_modules/@types" --types node \
    --module nodenext --target es2023 --allowImportingTsExtensions \
    "$run/integrations/opencode/skill-eval/index.ts" "$run/tests/skill-eval.test.ts"
node --test "$run/tests/skill-eval.test.ts"
