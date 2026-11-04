#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROUP="$1"
RUN="$(mktemp -d "${TMPDIR:-/tmp/opencode}/rules.XXXXXX")"
trap 'rm -rf "$RUN"' EXIT
export HOME="$RUN/home space" XDG_CONFIG_HOME="$RUN/config space"
USER_DIR="$XDG_CONFIG_HOME/opencode/data/cc-thingz/$GROUP"
mkdir -p "$RUN/work space/.opencode" "$USER_DIR" "$RUN/explicit space"
ln -s "$ROOT/plugins/$GROUP/scripts/resolve-rules.sh" "$RUN/linked resolver"
SCRIPT="$RUN/linked resolver"
cd "$RUN/work space"
filename="$GROUP-rules.md"
count=0
check() {
    local expected="$1"
    shift
    local actual
    actual="$(bash "$SCRIPT" "$@")"
    if [ "$actual" != "$expected" ]; then
        printf 'FAIL %s: expected <%s>, got <%s>\n' "$GROUP" "$expected" "$actual" >&2
        exit 1
    fi
    count=$((count + 1))
}
check "" "$filename"
printf 'project' > ".opencode/$filename"
check project "$filename"
printf 'user' > "$USER_DIR/$filename"
check project "$filename"
rm ".opencode/$filename"
check user "$filename"
touch ".opencode/$filename"
check user "$filename"
rm "$USER_DIR/$filename"
check "" "$filename"
touch "$USER_DIR/$filename"
check "" "$filename"
check ""
printf 'explicit' > "$RUN/explicit space/$filename"
printf 'user' > "$USER_DIR/$filename"
check explicit "$filename" "$RUN/explicit space"
check user "$filename" ""
# HOME fallback with unset and empty XDG; old Claude environment has no effect.
mkdir -p "$HOME/.config/opencode/data/cc-thingz/$GROUP"
printf 'home' > "$HOME/.config/opencode/data/cc-thingz/$GROUP/$filename"
unset XDG_CONFIG_HOME
export CLAUDE_PLUGIN_DATA="$RUN/explicit space"
check home "$filename"
export XDG_CONFIG_HOME=""
check home "$filename"
# Read-only resolution accepts a user-provided symlink and preserves whitespace.
printf '  \n' > "$RUN/whitespace"
ln -sf "$RUN/whitespace" ".opencode/$filename"
check '  ' "$filename"
# A selected file that cannot be read is an error, not empty/missing rules.
mkdir "$RUN/bin"
printf '#!/bin/bash\necho "fixture read failure" >&2\nexit 7\n' > "$RUN/bin/cat"
chmod +x "$RUN/bin/cat"
rc=0
PATH="$RUN/bin:$PATH" bash "$SCRIPT" "$filename" > "$RUN/stdout" 2> "$RUN/stderr" || rc=$?
[ "$rc" -eq 7 ] && [ ! -s "$RUN/stdout" ] && grep -q 'fixture read failure' "$RUN/stderr"
count=$((count + 1))
echo "$GROUP rules: $count passed"
