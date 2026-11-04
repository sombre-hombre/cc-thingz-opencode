#!/bin/bash
# copy a bundled prompt or agent file to an override location for editing
# usage: customize-file.sh <relative-path> [data-dir]
# e.g.: customize-file.sh prompts/review.md
# e.g.: customize-file.sh agents/quality.txt /path/to/plugin/data
#
# with a data-dir, copies to <data-dir>/<path> (user level, all projects).
# without one, copies to .opencode/exec-plan/<path> (project level).
# Pass "--user" as data-dir to use the XDG planning data directory.
# Only the requested file is copied; resolution never seeds defaults.
#
# an override shadows the bundled default permanently -- see the "Customization"
# paragraph of README.md, which is authoritative for the consequences
#
# refuses to overwrite an existing override; prints the destination path

set -e

path="${1:-}"
if [ -z "$path" ]; then
    echo "error: usage: customize-file.sh <relative-path> [data-dir]" >&2
    exit 1
fi

case "$path" in
    /*|../*|*/../*|*/..|..)
        echo "error: path must be relative and stay inside the override dir: $path" >&2
        exit 1
        ;;
esac

# Normalize trailing slashes so the ancestor walk stops at the selected root.
data_dir="${2:-}"
if [ "$data_dir" = "--user" ]; then
    data_dir="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning"
fi
while [ "$data_dir" != "${data_dir%/}" ]; do
    data_dir="${data_dir%/}"
done

# A passed-but-empty data dir must not silently become a project-level copy.
if [ "$#" -ge 2 ] && [ -z "$data_dir" ]; then
    echo "error: data-dir argument is empty or the filesystem root; use --user for XDG data or omit the argument for a project-level copy" >&2
    exit 1
fi

# derive skill root from script location: <skill-root>/scripts/customize-file.sh
SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"

src="$SKILL_ROOT/references/$path"
if [ ! -f "$src" ]; then
    echo "error: no bundled file at $path" >&2
    exit 1
fi

if [ -n "$data_dir" ]; then
    dest="$data_dir/$path"
else
    dest=".opencode/exec-plan/$path"
fi

# -L as well as -e: a dangling symlink is invisible to -e, and cp would follow it
# and write outside the override directory, defeating the path guard above
if [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "error: override already exists, edit it in place: $dest" >&2
    exit 1
fi

# the -e/-L check above only covers the destination file. any ancestor directory can
# be a symlink too: mkdir -p accepts it and cp follows it, so the copy lands outside
# the override dir. walk the components at or below the override root and refuse any
# symlink among them. components above the root are not checked -- the data dir comes
# from the caller, and a symlinked $HOME or XDG config is a legitimate setup.
#
# the two branches are deliberately asymmetric: at project level the walk stops at the
# working directory, so `.opencode` itself is checked too. that is stricter than the
# user-level exemption on purpose -- `.opencode` comes out of the checked-out repository,
# not the caller, so a repo shipping `.opencode` as a symlink could redirect the
# copy anywhere. someone whose `.opencode` is symlinked into a dotfiles repo gets a clear
# error and can use the user-level data dir instead
if [ -n "$data_dir" ]; then
    stop="$data_dir"
else
    stop="."
fi
# "." terminates the walk as well as "/": dirname "." is ".", so a $stop that is somehow
# absent from the chain would otherwise spin here forever rather than fail
dir="$(dirname "$dest")"
while [ "$dir" != "$stop" ] && [ "$dir" != "/" ] && [ "$dir" != "." ]; do
    if [ -L "$dir" ]; then
        echo "error: refusing to write through a symlinked directory component: $dir" >&2
        exit 1
    fi
    dir="$(dirname "$dir")"
done

mkdir -p "$(dirname "$dest")"
cp "$src" "$dest"
echo "$dest"
