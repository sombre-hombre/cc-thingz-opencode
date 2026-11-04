#!/usr/bin/env python3
"""Explicit terminal handoff. stdout is never the annotations/status channel."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class Cancelled(Exception):
    pass


def cancelled(signum, frame):
    raise Cancelled(f"launcher received signal {signum}")


def atomic_text(path, text):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def worker(request):
    """Runs on the selected TTY; writes actual revdiff status, not terminal's."""
    data = json.loads(Path(request).read_text())
    root = Path(request).parent
    child = None
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, cancelled)
    try:
        with (root / "revdiff.stderr").open("wb") as err:
            # Serialize startup against cancellation before a PID exists. An
            # already queued popup must not start revdiff after parent cleanup.
            with (root / "startup.lock").open("r+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if (root / "cancel").exists() or not Path(request).exists():
                    return
                atomic_text(root / "worker.pid", str(os.getpid()))
                child = subprocess.Popen(data["argv"], stderr=err)
                atomic_text(root / "child.pid", str(child.pid))
            code = child.wait()
        (root / "exit.tmp").write_text(str(code))
        (root / "exit.tmp").replace(root / "exit")
    except Cancelled:
        (root / "worker.cancelled").touch()
    finally:
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        terminate(child)


def terminate(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # POSIX ps works on Linux and macOS; a zombie is not a live TTY worker.
    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=2)
    if status.returncode:
        if status.returncode == 1 and not status.stdout.strip() and not status.stderr.strip():
            return False  # PID exited between kill(0) and ps.
        raise OSError(f'cannot inspect terminal worker: {status.stderr.strip()}')
    return bool(status.stdout.strip()) and not status.stdout.lstrip().startswith('Z')


def wait_handoff(process, run, timeout):
    """A launcher's successful/daemonized exit is never a review result."""
    deadline = time.monotonic() + timeout
    launch_exited = None
    while time.monotonic() < deadline:
        code = process.poll()
        if code not in (None, 0):
            raise ValueError("terminal launch failed; see terminal_stderr; verify display/session access")
        if (run / "exit").exists():
            return code
        if (run / "worker.cancelled").exists():
            raise Cancelled("terminal window closed or worker interrupted; not approved")
        pidfile = run / "worker.pid"
        if pidfile.exists():
            if not alive(int(pidfile.read_text())) and not (run / "exit").exists():
                raise Cancelled("terminal worker disappeared without handoff; not approved")
        elif code == 0:
            if launch_exited is None:
                launch_exited = time.monotonic()
            if time.monotonic() - launch_exited > 5:
                raise ValueError("terminal exited without starting review worker; verify display/session access")
        time.sleep(.05)
    raise Cancelled("review timed out; not approved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs='?')
    parser.add_argument("--check-status", help="revalidate reviewed bytes immediately after confirmation")
    parser.add_argument("--output", help="annotations file, must not exist")
    parser.add_argument("--status", help="JSON status file, must not exist")
    parser.add_argument("--tmux-socket")
    parser.add_argument("--tmux-client")
    parser.add_argument("--tmux-pane")
    parser.add_argument("--terminal", "--backend", choices=("tmux", "kitty-window", "foot-window", "kitty-overlay"), default="tmux")
    parser.add_argument("--kitty-socket", help="explicit existing remote-control address; never enabled by launcher")
    parser.add_argument("--kitty-window-id", type=int)
    parser.add_argument("--wayland-display", help="explicit client display override for separate window")
    parser.add_argument("--display", help="explicit X11 display override for separate window")
    parser.add_argument("--xdg-runtime-dir", help="explicit client runtime directory override")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--exit-code-on-annotations", action="store_true")
    args = parser.parse_args()
    if args.check_status:
        status = Path(args.check_status)
        try:
            result = json.loads(status.read_text())
            if result['state'] not in ('annotations', 'needs-confirmation'):
                raise ValueError('status is not a completed snapshot review')
            if hashlib.sha256(Path(result['plan']).read_bytes()).hexdigest() != result['snapshot_sha256']:
                result.update(state='stale', reason='plan changed after review; reopen before approval')
                status.write_text(json.dumps(result, indent=2) + '\n')
                raise ValueError(result['reason'])
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'error: {exc}', file=sys.stderr)
            return 1
    if not args.plan or not args.output or not args.status:
        parser.error('plan, --output and --status required')
    output, status = Path(args.output).absolute(), Path(args.status).absolute()
    plan = Path(args.plan).resolve()
    # Exclusive creation prevents stale output, accidental overwrite and aliases.
    try:
        with status.open("x"):
            pass
        with output.open("x"):
            pass
    except OSError as exc:
        print(f"error: cannot create fresh handoff files: {exc}", file=sys.stderr)
        return 2
    result = {"state": "failed", "plan": str(plan), "annotations": str(output),
              "revdiff_exit": None, "terminal_exit": None}
    popup = None
    remote = None
    overlay_id = None
    run = None
    rc = 1
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, cancelled)
    try:
        if os.environ.get("PLANNING_DISABLE_REVDIFF"):
            result.update(state="skipped", reason="PLANNING_DISABLE_REVDIFF")
            rc = 0
            return rc
        if args.timeout <= 0 or not args.timeout < float("inf"):
            raise ValueError("timeout must be finite and positive")
        original = plan.read_bytes()
        if args.terminal != "tmux" and any((args.tmux_socket, args.tmux_client, args.tmux_pane)):
            raise ValueError("tmux target flags conflict with selected --terminal")
        if args.terminal != "kitty-overlay" and any((args.kitty_socket, args.kitty_window_id is not None)):
            raise ValueError("Kitty target flags require --terminal kitty-overlay")
        revdiff = shutil.which("revdiff")
        if not revdiff:
            raise ValueError("missing dependency: revdiff")
        terminal_env = dict(os.environ)
        for key, value in (("WAYLAND_DISPLAY", args.wayland_display), ("DISPLAY", args.display),
                           ("XDG_RUNTIME_DIR", args.xdg_runtime_dir)):
            if value is not None:
                terminal_env[key] = value
        if args.terminal == "tmux":
            terminal_info, base = tmux_target(args, result)
        else:
            name = "foot" if args.terminal == "foot-window" else "kitty"
            executable = shutil.which(name)
            if not executable:
                raise ValueError(f"missing dependency: {name}; select an installed --terminal")
            terminal_info = {"backend": args.terminal, "executable": executable}
            if args.terminal == "kitty-overlay":
                if not args.kitty_socket or args.kitty_window_id is None or args.kitty_window_id <= 0:
                    raise ValueError("explicit --kitty-socket and positive --kitty-window-id required; use kitty-window without remote control")
                remote = [executable, "@", "--to", args.kitty_socket]
                response = subprocess.run(remote + ["ls"], capture_output=True, text=True, timeout=5)
                if response.returncode:
                    result["terminal_stderr"] = response.stderr
                    raise ValueError("Kitty remote control unavailable; use --terminal kitty-window (no configuration required)")
                windows = [w for osw in json.loads(response.stdout) for tab in osw["tabs"] for w in tab["windows"]]
                if sum(w["id"] == args.kitty_window_id for w in windows) != 1:
                    raise ValueError("explicit Kitty window ID not found on selected socket")
                terminal_info.update(socket=args.kitty_socket, window_id=args.kitty_window_id)
            elif args.terminal == 'foot-window' and sys.platform == 'darwin':
                raise ValueError('foot requires Linux/Wayland; use kitty-window or tmux on macOS')
            elif sys.platform != 'darwin' and not (terminal_env.get("DISPLAY") or (terminal_env.get("WAYLAND_DISPLAY") and terminal_env.get("XDG_RUNTIME_DIR"))):
                raise ValueError("graphical display unavailable; supply client --wayland-display and --xdg-runtime-dir (or --display); do not infer a compositor")
        run = Path(tempfile.mkdtemp(prefix="plan-review-", dir="/tmp/opencode"))
        snapshot = run / "snapshot" / plan.name
        snapshot.parent.mkdir()
        snapshot.write_bytes(original)
        empty = run / "empty"
        empty.touch()
        result.update(snapshot_sha256=hashlib.sha256(original).hexdigest(),
                      snapshot_text=original.decode("utf-8"), annotation_file=plan.name,
                      terminal=terminal_info)
        argv = [str(Path(revdiff).resolve()), "--compare-old", str(empty),
                "--compare-new", str(snapshot), "--output", str(run / "annotations"),
                "--wrap", "--history-dir", str(run / "history")]
        if args.exit_code_on_annotations:
            argv.append("--exit-code-on-annotations")
        request = run / "request.json"
        request.write_text(json.dumps({"argv": argv}))
        (run / "startup.lock").touch()
        worker_argv = [sys.executable, str(Path(__file__).resolve()), "--worker", str(request)]
        if args.terminal == "tmux":
            # Only tmux requires shell-command encoding; other terminals use argv.
            popup_args = base + ["display-popup", "-c", args.tmux_client, "-t", args.tmux_pane,
                                "-E", "-w", os.environ.get("REVDIFF_POPUP_WIDTH", "90%"),
                                "-h", os.environ.get("REVDIFF_POPUP_HEIGHT", "90%"),
                                "-T", f"plan: {plan.name}", "--", shlex.join(worker_argv)]
        elif remote:
            popup_args = remote + ["launch", "--type", "overlay", "--match", f"window_id:{args.kitty_window_id}",
                                   "--next-to", f"id:{args.kitty_window_id}", "--source-window", f"id:{args.kitty_window_id}",
                                   "--title", f"plan: {plan.name}", "--cwd", str(run), "--"] + worker_argv
        elif args.terminal == "kitty-window":
            popup_args = [executable, "--config", "NONE", "--title", f"plan: {plan.name}", "--"] + worker_argv
        else:
            popup_args = [executable, "--title", f"plan: {plan.name}", "--"] + worker_argv
        with (run / "terminal.stdout").open("wb") as out, (run / "terminal.stderr").open("wb") as err:
            deadline = time.monotonic() + args.timeout
            popup = subprocess.Popen(popup_args, stdout=out, stderr=err, env=terminal_env)
            try:
                if args.terminal == "tmux":
                    result["terminal_exit"] = popup.wait(timeout=args.timeout)
                else:
                    if remote:
                        popup.wait(timeout=min(10, args.timeout))
                        if popup.returncode != 0:
                            raise ValueError("Kitty overlay launch failed; use --terminal kitty-window")
                        overlay_id = int((run / "terminal.stdout").read_text().strip())
                        if overlay_id <= 0 or overlay_id == args.kitty_window_id:
                            overlay_id = None
                            raise ValueError("invalid created Kitty overlay ID")
                        result["terminal"]["overlay_id"] = overlay_id
                    result["terminal_exit"] = wait_handoff(popup, run, max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise Cancelled("review timed out; not approved")
            finally:
                result["terminal_exit"] = popup.poll()
                result["terminal_stderr"] = (run / "terminal.stderr").read_text(errors="replace")
        result["revdiff_stderr"] = ((run / "revdiff.stderr").read_text(errors="replace")
                                    if (run / "revdiff.stderr").exists() else "")
        if result["terminal_exit"] not in (None, 0):
            raise ValueError("terminal failed; see terminal_stderr")
        if not (run / "exit").exists():
            raise Cancelled("terminal closed without revdiff handoff; not approved")
        code = int((run / "exit").read_text())
        result["revdiff_exit"] = code
        annotations = (run / "annotations").read_bytes() if (run / "annotations").exists() else b""
        if code != 0 and not (code == 10 and args.exit_code_on_annotations and annotations):
            raise ValueError(f"revdiff failed with exit {code}")
        if plan.read_bytes() != original:
            result["state"] = "stale"
            raise ValueError("plan changed during review; rerun before applying line annotations")
        output.write_bytes(annotations)
        result["state"] = "annotations" if annotations else "needs-confirmation"
        rc = 0
    except Cancelled as exc:
        result.update(state="cancelled", reason=str(exc))
        rc = 130
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result["reason"] = str(exc)
        print(f"error: {exc}", file=sys.stderr)
    finally:
        # Ignore repeated cancellation only while performing bounded cleanup.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if run is not None:
            with (run / "startup.lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                (run / "cancel").touch()
            pidfile = run / "worker.pid"
            if pidfile.exists() and not (run / "exit").exists():
                pid = int(pidfile.read_text())
                try:
                    os.kill(pid, signal.SIGTERM)
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and alive(pid):
                        time.sleep(0.05)
                    if alive(pid):
                        if (run / "child.pid").exists():
                            try:
                                os.kill(int((run / "child.pid").read_text()), signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                # A force-killed worker cannot reap/terminate its revdiff child.
                childfile = run / "child.pid"
                if childfile.exists():
                    child_pid = int(childfile.read_text())
                    if alive(child_pid):
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        terminate(popup)
        if remote and overlay_id is not None:
            # Never close the user's target window, only our created overlay.
            try:
                subprocess.run(remote + ["close-window", "--match", f"id:{overlay_id}"],
                               capture_output=True, timeout=3)
            except (OSError, subprocess.SubprocessError):
                pass
        if run is not None:
            shutil.rmtree(run)
        status.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return rc


def tmux_target(args, result):
    if not all((args.tmux_socket, args.tmux_client, args.tmux_pane)):
        raise ValueError("explicit --tmux-socket, --tmux-client and --tmux-pane required")
    if not args.tmux_pane.startswith("%") or not args.tmux_pane[1:].isdigit():
        raise ValueError("tmux pane must be an exact %N pane ID")
    tmux = shutil.which("tmux")
    if not tmux:
        raise ValueError("missing dependency: tmux")
    base = [tmux, "-S", args.tmux_socket]

    def query(*cmd):
        response = subprocess.run(base + list(cmd), capture_output=True,
                                  text=True, timeout=5)
        if response.returncode:
            result["terminal_stderr"] = response.stderr
            raise ValueError(f"tmux target validation failed (exit {response.returncode}): {response.stderr.strip()}")
        return response.stdout.strip()

    clients = query("list-clients", "-F", "#{client_name}\t#{session_id}")
    selected = [line.split("\t") for line in clients.splitlines()
                if line.split("\t")[0] == args.tmux_client]
    if len(selected) != 1 or len(selected[0]) != 2:
        raise ValueError("selected tmux client not attached or not unique")
    pane = query("display-message", "-p", "-t", args.tmux_pane,
                 "#{pane_id}\t#{session_id}").split("\t")
    if pane != [args.tmux_pane, selected[0][1]]:
        raise ValueError("selected pane does not belong to selected client's session")
    return {"backend": "tmux", "socket": args.tmux_socket,
            "client": args.tmux_client, "pane": args.tmux_pane}, base


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
    else:
        sys.exit(main())
