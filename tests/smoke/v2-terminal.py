"""Owned tmux clients: real server shell -> explicit client popup -> revdiff.

The two clients are invisible PTYs, never the user's terminal. All tmux calls
use our private socket. This proves explicit targeting, not automatic selection
of the client attached to the user's OpenCode TUI.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time


def probe(api, sid, run, env):
    socket = str(run / "tmux.sock")
    clean = {**env, "TERM": "xterm-256color"}
    command = ["/usr/bin/tmux", "-S", socket, "-f", "/dev/null"]
    def tmux(*argv):
        return subprocess.check_output([*command, *argv], env=clean, text=True).strip()
    clients = []
    try:
        tmux("new-session", "-d", "-s", "chosen", "-x", "120", "-y", "40", "sleep", "120")
        tmux("new-session", "-d", "-s", "other", "-x", "120", "-y", "40", "sleep", "120")
        for name in ["chosen", "other"]:
            pid, fd = pty.fork()
            if pid == 0:
                os.execve(command[0], [*command, "attach-session", "-t", name], clean)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
            clients.append((pid, fd))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            inventory = tmux("list-clients", "-F", "#{client_name}|#{session_name}")
            if len(inventory.splitlines()) == 2:
                break
            time.sleep(0.1)
        names = dict(line.split("|", 1)[::-1] for line in inventory.splitlines())
        assert set(names) == {"chosen", "other"}
        plan = run / "terminal plan.md"
        plan.write_text("# TARGETED_REVIEW_ONLY\n\nFull last line\n")
        empty = run / "empty.md"
        empty.write_text("")
        # The test does not rely on any server KITTY_*/TMUX value.
        review = shlex.join(["/usr/bin/revdiff", "--compare-old", str(empty), "--compare-new", str(plan),
                             "--no-mouse", "-o", str(run / "terminal.annotations.md")])
        launch = shlex.join([*command, "display-popup", "-c", names["chosen"], "-t", "chosen:0.0",
                            "-E", "-w", "90%", "-h", "90%", review])
        launch_results = []
        def launch_popup():
            try:
                launch_results.append(api("POST", f"/api/session/{sid}/shell", {"command": launch}))
            except Exception as error:
                launch_results.append(error)
        thread = threading.Thread(target=launch_popup, daemon=True)
        thread.start()
        screens = [b"", b""]
        deadline = time.monotonic() + 15
        found = False
        while time.monotonic() < deadline:
            for index, (_, fd) in enumerate(clients):
                if select.select([fd], [], [], 0.05)[0]:
                    chunk = os.read(fd, 65536)
                    screens[index] += chunk
                    if b"\x1b[6n" in chunk:
                        os.write(fd, b"\x1b[1;1R")
                    if b"]11;?" in chunk:
                        os.write(fd, b"\x1b]11;rgb:0000/0000/0000\x1b\\")
            if b"TARGETED_REVIEW_ONLY" in screens[0]:
                found = True
                os.write(clients[0][1], b"q")
                break
        for index, screen in enumerate(screens):
            (run / f"tmux-client-{index}.screen").write_bytes(screen)
        assert found, "server popup never reached selected owned client"
        assert b"TARGETED_REVIEW_ONLY" not in screens[1], "popup reached wrong client"
        thread.join(timeout=10)
        assert not thread.is_alive() and launch_results == [None], launch_results
        context = api("GET", f"/api/session/{sid}/context")
        (run / "terminal-context.json").write_text(json.dumps(context, indent=2))
        completed = [m for m in context["data"] if m.get("type") == "shell" and m.get("command") == launch]
        assert completed and completed[-1].get("exit") == 0, completed
        return {"clients": 2, "selected": "chosen", "other_received_review": False,
                "backend": "tmux explicit socket + client + pane", "popup_exit": 0,
                "review_status": "needs-confirmation"}
    finally:
        # This is only the private test socket, never the user's tmux server.
        if Path(socket).exists():
            subprocess.run([*command, "kill-server"], env=clean, capture_output=True)
        for pid, fd in clients:
            os.close(fd)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
