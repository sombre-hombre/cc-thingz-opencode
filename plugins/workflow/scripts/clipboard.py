#!/usr/bin/env python3
"""Copy an already prepared UTF-8 file, without reading the clipboard.

Part of the cc-thingz OpenCode port (MIT); backend order derives from the
upstream workflow skills, with Wayland support added by the port.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BACKEND_TIMEOUT = 10


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        content = args.file.read_bytes()
        characters = len(content.decode("utf-8"))
        candidates = []
        if sys.platform == "darwin":
            candidates.append(["pbcopy"])
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            candidates.append(["wl-copy", "--type", "text/plain;charset=utf-8"])
        candidates.extend((["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]))
        command = next((cmd for cmd in candidates if shutil.which(cmd[0])), None)
        if command is None:
            raise RuntimeError("No clipboard backend found: install wl-copy (Wayland), pbcopy (macOS), xclip or xsel (X11)")
        # Never read a selection, normalize text, add a newline, or silently
        # switch displays/backends after a failure. Selection owners daemonize
        # with inherited stdio: regular files avoid waiting for their pipe EOF,
        # including during timeout cleanup. Only the launcher must finish.
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as errors:
            source.write(content)
            source.seek(0)
            try:
                result = subprocess.run(command, stdin=source, stdout=subprocess.DEVNULL,
                                        stderr=errors, timeout=BACKEND_TIMEOUT, check=False)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"{command[0]} timed out after {BACKEND_TIMEOUT}s") from None
            if result.returncode:
                errors.seek(0)
                error = errors.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"{command[0]} failed (exit {result.returncode}): {error}")
        print(f"Copied to clipboard ({characters} characters; {len(content)} bytes; {command[0]})")
        return 0
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"clipboard: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
