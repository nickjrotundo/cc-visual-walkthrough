"""`ccwalk serve`: a local report server with a generated runs index.

The runner writes each tour into reports/walkthrough/<timestamp>/, which
is fine on a desktop and useless over ssh/WSL2/cloud boxes where "just
open the file" is not a thing. This serves the report directory over
HTTP with a generated index at / -- one row per run, newest first, with
its PASS/WARN/FAIL counts pulled from run_meta.json -- so the browsing
story matches the original internal reports listing.

Mechanics:
- The index is rebuilt per request (runs appear/prune between requests)
  and every response carries Cache-Control: no-store.
- Anything that isn't / is served statically from the report out_dir
  only (resolved-path containment; nothing else is reachable).
- `--daemon` runs the server as a detached child; `.ccwalk/serve.pid`
  records {pid, port, bind} and `serve stop` / `serve status` manage it.
  A pidfile whose pid is dead or belongs to a foreign process (cmdline
  does not look like ccwalk) is treated as stale and cleaned, never
  killed.
- stdlib http.server: no Range support, so Safari will not play the
  .webm videos from here -- Chromium-family browsers play them fine, and
  the documented Safari story stays `--mp4` + a range-capable server.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html import escape as _esc
from pathlib import Path

DEFAULT_PORT = 8378  # ccdoing's serve sits on 8377; keep the pair adjacent
STATE_DIRNAME = ".ccwalk"
PIDFILE_NAME = "serve.pid"
LOGFILE_NAME = "serve.log"

_BADGE_COLORS = {"pass": "#2ecc71", "warn": "#f39c12", "fail": "#e74c3c", "blocked": "#8b9bb4"}


# --------------------------------------------------------------------------
# Runs index


@dataclass
class RunRow:
    run_id: str
    ok: bool = True  # run_meta.json was readable
    counts: dict[str, int] = field(default_factory=dict)  # pass/warn/fail/blocked
    total: int = 0
    spec: str = ""
    git_head: str = ""
    duration_ms: float = 0.0
    has_report: bool = False


def scan_runs(out_root: Path) -> list[RunRow]:
    """One row per run directory under out_root, newest first. Run dirs
    are named UTC timestamps, so reverse-name order is reverse-chronological
    (non-conforming names still sort deterministically)."""
    rows: list[RunRow] = []
    if not out_root.is_dir():
        return rows
    for d in sorted((p for p in out_root.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        row = RunRow(run_id=d.name, has_report=(d / "report.html").is_file())
        meta_path = d / "run_meta.json"
        try:
            meta = json.loads(meta_path.read_text())
            results = meta.get("results", [])
            counts = {"pass": 0, "warn": 0, "fail": 0, "blocked": 0}
            duration = 0.0
            for r in results:
                s = r.get("status", "")
                if s in counts:
                    counts[s] += 1
                try:
                    duration += float(r.get("duration_ms") or 0)
                except (TypeError, ValueError):
                    pass
            row.counts = counts
            row.total = len(results)
            row.spec = str(meta.get("spec", ""))
            row.git_head = str(meta.get("git_head", ""))
            row.duration_ms = duration
        except Exception:  # noqa: BLE001 - unreadable meta is a row, not a crash
            row.ok = False
        rows.append(row)
    return rows


def _result_cell(row: RunRow) -> str:
    if not row.ok:
        return '<span style="color:#8b9bb4;">(unreadable)</span>'
    c = row.counts
    parts = [f"{c.get('pass', 0)}/{row.total} passed"]
    for kind in ("warn", "fail", "blocked"):
        if c.get(kind):
            parts.append(
                f'<span style="color:{_BADGE_COLORS[kind]};">{c[kind]} {kind}</span>'
            )
    return " &middot; ".join(parts)


def render_index_html(rows: list[RunRow], app_name: str = "") -> str:
    title = f"{app_name} walkthrough reports" if app_name else "Walkthrough reports"
    if rows:
        body_rows = []
        for row in rows:
            rid = _esc(row.run_id)
            link = (
                f'<a href="/{urllib.parse.quote(row.run_id)}/report.html">{rid}</a>'
                if row.has_report else rid
            )
            dur = f"{row.duration_ms / 1000:.1f}s" if row.ok and row.duration_ms else ""
            body_rows.append(
                f"<tr><td>{link}</td><td>{_result_cell(row)}</td>"
                f"<td><code>{_esc(row.spec)}</code></td>"
                f"<td><code>{_esc(row.git_head)}</code></td>"
                f"<td>{_esc(dur)}</td></tr>"
            )
        table = (
            "<table><thead><tr><th>Run</th><th>Result</th><th>Spec</th>"
            "<th>Git</th><th>Duration</th></tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )
    else:
        table = "<p>No runs yet &mdash; run <code>ccwalk run</code> first.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#0b0e14; color:#e6e6e6; font-family: -apple-system, Segoe UI, sans-serif;
          max-width: 1000px; margin: 0 auto; padding: 24px; line-height: 1.5; }}
  h1 {{ margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%;
           background:#151a24; border:1px solid #262b38; border-radius:10px; }}
  th, td {{ text-align: left; padding: 8px 14px; border-bottom: 1px solid #262b38; }}
  th {{ color:#8b9bb4; font-weight:600; font-size:0.9em; }}
  tr:last-child td {{ border-bottom: none; }}
  a {{ color:#7aa2f7; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  code {{ background:#0b0e14; padding:1px 5px; border-radius:4px; font-size:0.9em; }}
</style>
</head>
<body>
<h1>{_esc(title)}</h1>
{table}
</body></html>
"""


# --------------------------------------------------------------------------
# HTTP server


class ReportsHandler(http.server.BaseHTTPRequestHandler):
    """Index at /, static passthrough (containment-checked) for the rest,
    Cache-Control: no-store on every response including 404s."""

    server_version = "ccwalk"
    out_root: Path  # set via make_server's handler subclass
    app_name: str = ""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _404(self, why: str = "not found") -> None:
        self._send(404, f"<h1>404</h1><p>{_esc(why)}</p>".encode(),
                   "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        first = args[0] if args and isinstance(args[0], str) else ""
        if "favicon.ico" in first:
            return
        super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            html = render_index_html(scan_runs(self.out_root), self.app_name)
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        root = self.out_root.resolve()
        target = (root / path.lstrip("/")).resolve()
        try:
            inside = target.is_relative_to(root)
        except AttributeError:  # pragma: no cover - 3.11 floor has it
            inside = str(target).startswith(str(root) + os.sep)
        if not inside or not target.is_file():
            self._404("only files under the report directory are served")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        try:
            self._send(200, target.read_bytes(), ctype)
        except OSError:
            self._404("unreadable")


def make_server(
    out_root: Path, app_name: str = "", port: int = DEFAULT_PORT,
    bind: str = "127.0.0.1",
) -> http.server.ThreadingHTTPServer:
    handler = type("Handler", (ReportsHandler,),
                   {"out_root": out_root, "app_name": app_name})
    return http.server.ThreadingHTTPServer((bind, port), handler)


# --------------------------------------------------------------------------
# Pidfile + daemon lifecycle


def _state_dir(project_root: Path) -> Path:
    d = project_root / STATE_DIRNAME
    d.mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")  # the state dir ignores itself
    return d


def _pidfile(project_root: Path) -> Path:
    return _state_dir(project_root) / PIDFILE_NAME


def _pid_is_ours(pid: int) -> bool | None:
    """Best-effort guard against pid reuse: only pids whose command line
    looks like a ccwalk process are ever treated as our server.

    Returns True/False when a command line could be read (via /proc on
    Linux, `ps` elsewhere, e.g. macOS which has no /proc), and None when
    NEITHER source is available - callers must treat None as "unknown"
    and never auto-clean a live pid on it (refusing to clean beats
    orphaning a live daemon)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        return b"ccwalk" in cmdline or b"cc_visual_walkthrough" in cmdline
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return False  # ps ran and found no such pid
        cmd = out.stdout.strip()
        if not cmd:
            return None
        return "ccwalk" in cmd or "cc_visual_walkthrough" in cmd
    except (OSError, subprocess.SubprocessError):
        return None


def write_pidfile(project_root: Path, pid: int, port: int, bind: str) -> None:
    _pidfile(project_root).write_text(
        json.dumps({"pid": pid, "port": port, "bind": bind})
    )


def daemon_status(project_root: Path) -> dict | None:
    """The recorded server if it is genuinely alive, else None (stale
    pidfiles -- dead pid, or a reused pid that isn't ccwalk -- are removed)."""
    pf = _pidfile(project_root)
    try:
        info = json.loads(pf.read_text())
        pid = int(info["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    except PermissionError:
        alive = True  # exists, not ours to signal -- but then it isn't ours at all
    if not alive:
        pf.unlink(missing_ok=True)
        return None
    ours = _pid_is_ours(pid)
    if ours is False:
        # Live pid that is provably not a ccwalk process: reused pid.
        pf.unlink(missing_ok=True)
        return None
    if ours is None:
        # Live pid, but no way to inspect its command line on this
        # platform: assume it is ours rather than delete the pidfile and
        # orphan a live daemon (stop would then be impossible via ccwalk).
        info["unverified"] = True
    return info


def _url(info: dict) -> str:
    host = info.get("bind", "127.0.0.1")
    if host == "0.0.0.0":  # noqa: S104 - display only
        host = "<this-host>"
    return f"http://{host}:{info['port']}/"


def _free_port(bind: str) -> int:
    with socket.socket() as s:
        s.bind((bind, 0))
        return s.getsockname()[1]


def _print_started(info: dict, out_root: Path) -> None:
    print(f"Reports index: {_url(info)}  (newest run first; no-store on all responses)")
    if _is_wsl():
        print("WSL2: localhost usually works from the Windows browser, but not"
              " always - if not, open it in a Linux browser (e.g. WSLg Chrome).")
    if not any(out_root.glob("*/report.html")):
        print("note: no runs yet - `ccwalk run` will populate the index")


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def stop(project_root: Path) -> int:
    info = daemon_status(project_root)
    if info is None:
        print("ccwalk serve: not running")
        return 0
    pid = int(info["pid"])
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    _pidfile(project_root).unlink(missing_ok=True)
    print(f"ccwalk serve: stopped (pid {pid})")
    return 0


def status(project_root: Path, out_root: Path) -> int:
    info = daemon_status(project_root)
    if info is None:
        print("ccwalk serve: not running")
        return 3
    print(f"ccwalk serve: running (pid {info['pid']}) at {_url(info)}")
    return 0


def start(
    project_root: Path, out_root: Path, app_name: str = "",
    port: int = DEFAULT_PORT, bind: str = "127.0.0.1",
    daemon: bool = False, config_path: str | None = None,
) -> int:
    # Restart-on-start: starting while a server runs replaces it.
    if daemon_status(project_root) is not None:
        stop(project_root)

    if not daemon:
        try:
            httpd = make_server(out_root, app_name, port=port, bind=bind)
        except OSError as exc:
            import errno

            if exc.errno == errno.EADDRINUSE:
                print(
                    f"port {port} on {bind} is already in use. Check "
                    "`ccwalk serve status` (and `ccwalk serve stop`), or "
                    "pick another port with --port.",
                    file=sys.stderr,
                )
                return 1
            raise
        actual = httpd.server_address[1]
        info = {"pid": os.getpid(), "port": actual, "bind": bind}
        write_pidfile(project_root, **info)
        _print_started(info, out_root)
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
            _pidfile(project_root).unlink(missing_ok=True)
        return 0

    # Daemon: resolve the port up front (the child must bind a known one),
    # spawn a detached foreground `serve start`, wait for its pidfile.
    if port == 0:
        port = _free_port(bind)
    log = _state_dir(project_root) / LOGFILE_NAME
    cmd = [sys.executable, "-m", "cc_visual_walkthrough.cli", "serve", "start",
           "--port", str(port), "--bind", bind]
    if config_path:
        cmd += ["--config", config_path]
    with open(log, "ab") as lf:
        subprocess.Popen(cmd, cwd=project_root, stdout=lf, stderr=lf,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 10
    info = None
    while time.time() < deadline:
        info = daemon_status(project_root)
        if info is not None:
            try:
                urllib.request.urlopen(_url(info), timeout=1).read(64)
                break
            except OSError:
                pass
        time.sleep(0.15)
    if info is None:
        print(f"ccwalk serve: failed to start - see {log}", file=sys.stderr)
        return 1
    print(f"ccwalk serve: running in the background (pid {info['pid']})")
    _print_started(info, out_root)
    print("stop with: ccwalk serve stop")
    return 0
