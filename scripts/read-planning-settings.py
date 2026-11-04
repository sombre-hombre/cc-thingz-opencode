#!/usr/bin/env python3
"""Read user planning settings as JSON; never execute commands or read project settings."""

import json
import os
from pathlib import Path
import sys


DEFAULTS = {
    "external_review_cmd": "",
    "task_retries": 1,
    "review_iterations": 5,
    "external_review_iterations": 10,
    "finalize_enabled": True,
    "plans_dir": "docs/plans",
}


def read_settings(path):
    try:
        with path.open(encoding="utf-8") as stream:
            values = json.load(stream)
    except FileNotFoundError:
        # A dangling symlink is a broken configuration, not an absent optional file.
        if path.is_symlink():
            raise ValueError("settings symlink target does not exist")
        return DEFAULTS.copy()
    if not isinstance(values, dict):
        raise ValueError("expected a JSON object")
    unknown = values.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        if type(value) is not type(DEFAULTS[key]):
            raise ValueError(f"{key}: expected {type(DEFAULTS[key]).__name__}")
        if type(value) is int and value < 0:
            raise ValueError(f"{key}: expected a non-negative integer")
        if key == "plans_dir":
            directory = Path(value)
            if not value.strip() or directory.is_absolute() or ".." in directory.parts:
                raise ValueError("plans_dir: expected a non-empty project-relative directory without '..'")
    return DEFAULTS | values


def main():
    if len(sys.argv) > 2:
        print("usage: read-planning-settings.py [user-settings-file]", file=sys.stderr)
        return 2
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = Path(sys.argv[1]) if len(sys.argv) == 2 else config / "opencode/data/cc-thingz/planning/settings.json"
    try:
        settings = read_settings(path)
    except (OSError, ValueError) as error:
        print(f"error: planning settings {path}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(settings, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
