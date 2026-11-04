#!/usr/bin/env python3
"""Real revdiff contract probes in owned, invisible PTYs; no launcher fixture."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import tempfile
import termios
import time


def main():
    run = Path(tempfile.mkdtemp(prefix="cc-thingz-revdiff-pty.", dir="/tmp/opencode"))
    print(f"Artifacts: {run}", flush=True)
    (run / "home").mkdir()
    plan = run / "external plan.md"
    plan.write_text("# Contract plan\n\nFirst task\nLast line marker\n")
    empty = run / "empty.md"
    empty.write_text("")
    results = []
    for name, keys, sig, preload, code in [
        ("empty-q", b"q", None, False, 0),
        ("empty-Q", b"Q", None, False, 0),
        ("annotation-q", b"q", None, True, 10),
        ("annotation-Q", b"Qy", None, True, 0),
        ("empty-SIGINT", None, signal.SIGINT, False, 0),
        ("annotation-SIGTERM", None, signal.SIGTERM, True, 0),
    ]:
        output = run / f"{name}.annotations.md"
        argv = ["/usr/bin/revdiff", "--compare-old", str(empty), "--compare-new", str(plan),
                "--no-mouse", "--exit-code-on-annotations", "--history-dir", str(run / "history"), "-o", str(output)]
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(run)
            os.execve(argv[0], argv, {"PATH": "/usr/bin:/bin", "HOME": str(run / "home"), "TERM": "xterm-256color", "LANG": "C.UTF-8"})
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        screen = b""
        sent = False
        signal_ignored = False
        status = None
        deadline = time.monotonic() + 15
        started = time.monotonic()
        try:
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                        screen += chunk
                        if b"\x1b[6n" in chunk:
                            os.write(fd, b"\x1b[1;1R")
                        if b"]11;?" in chunk:
                            os.write(fd, b"\x1b]11;rgb:0000/0000/0000\x1b\\")
                    except OSError:
                        pass
                if not sent and b"Last line marker" in screen and time.monotonic() - started > 1.5:
                    if preload:
                        for chunk in [b"l", b"a", b"Contract annotation", b"\r"]:
                            os.write(fd, chunk)
                            time.sleep(0.2)
                    if sig:
                        os.kill(pid, sig)
                        if sig == signal.SIGINT:
                            time.sleep(0.3)
                            ended, _ = os.waitpid(pid, os.WNOHANG)
                            assert ended == 0, "SIGINT unexpectedly terminated revdiff"
                            signal_ignored = True
                            os.write(fd, b"q")
                    else:
                        for key in keys:
                            os.write(fd, bytes([key]))
                            time.sleep(0.1)
                    sent = True
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise RuntimeError(f"{name}: PTY timed out")
        finally:
            (run / f"{name}.screen").write_bytes(screen)
            os.close(fd)
        (run / f"{name}.screen").write_bytes(screen)
        actual_code = os.waitstatus_to_exitcode(status)
        text = output.read_text() if output.exists() else ""
        results.append({"probe": name, "exit": actual_code, "output": text,
                        "rendered_last_line": b"Last line marker" in screen,
                        "signal_ignored_then_q": signal_ignored})
        (run / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        assert actual_code == code, results[-1]
        assert bool(text) == (name == "annotation-q"), results[-1]
        assert b"Last line marker" in screen, "full external plan was not rendered"
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
