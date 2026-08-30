"""Small environment helpers shared across modules: .env reading, git
metadata, app readiness probing, viewport parsing, and dev-server
management for --start-app."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def read_env_var(name: str, env_path: Path | None = None) -> str | None:
    """Minimal .env parser (no python-dotenv dependency) -- reads a single
    KEY=VALUE line, skipping commented-out lines (# KEY=...)."""
    env_path = env_path or (Path.cwd() / ".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def get_env(name: str, env_path: Path | None = None) -> str:
    """Resolve a secret by name: process environment first, then .env."""
    if not name:
        return ""
    return os.environ.get(name) or read_env_var(name, env_path) or ""


def git_head(cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd or Path.cwd(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def app_ready(base_url: str, path: str = "/", timeout_s: int = 5) -> dict[str, Any]:
    """Best-effort readiness probe against the configured ready-check path.
    Used for the report header and the run preflight -- never fatal.
    ANY HTTP status counts as reachable: a 404 or 401 still means a
    server is up and answering (urllib raises HTTPError for >=400, but
    that is a response, not an outage)."""
    url = base_url.rstrip("/") + (path if path.startswith("/") else "/" + path)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return {"reachable": True, "status": resp.status}
    except urllib.error.HTTPError as e:
        return {"reachable": True, "status": e.code}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def parse_viewports(spec: str) -> list[tuple[int, int]]:
    """'390,768,1440' -> [(390, 844), (768, 1024), (1440, 900)] using a
    sensible default height per width, unless WxH pairs are given
    ('390x844,768x1024')."""
    out: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "x" in part:
            w_str, h_str = part.split("x", 1)
            out.append((int(w_str), int(h_str)))
        else:
            w = int(part)
            h = 844 if w <= 480 else (1024 if w <= 900 else 900)
            out.append((w, h))
    return out


class AppProcess:
    """Launches the configured dev server for the duration of a run
    (--start-app), polls the ready check, and tears the whole process
    GROUP down afterwards -- the shell wrapper dying is not proof its
    children (uvicorn, node, ...) died, so teardown escalates to SIGKILL
    on the recorded pgid whenever anything in the group survives.
    POSIX-only (os.killpg); --start-app is unsupported on native Windows."""

    _OUTPUT_TAIL_LINES = 30

    def __init__(self, start_command: str, base_url: str, ready_path: str = "/", timeout_s: int = 60):
        self.start_command = start_command
        self.base_url = base_url
        self.ready_path = ready_path
        self.timeout_s = timeout_s
        self.proc: subprocess.Popen | None = None
        self.pgid: int | None = None
        self._log_path: Path | None = None

    def _output_tail(self) -> str:
        if not self._log_path or not self._log_path.exists():
            return ""
        try:
            lines = self._log_path.read_text(errors="replace").splitlines()
        except OSError:
            return ""
        tail = "\n".join(lines[-self._OUTPUT_TAIL_LINES:])
        return f"\n--- app output (last {self._OUTPUT_TAIL_LINES} lines) ---\n{tail}" if tail else ""

    def __enter__(self) -> "AppProcess":
        # Imposter check: if the ready URL already answers, we would tour
        # whatever is squatting on the port while our own app fails to
        # bind -- refuse instead.
        pre = app_ready(self.base_url, self.ready_path, timeout_s=2)
        if pre.get("reachable"):
            raise RuntimeError(
                f"Something is already serving {self.base_url}{self.ready_path} "
                f"(HTTP {pre.get('status')}); refusing --start-app. Stop it first, "
                "or run without --start-app to tour the already-running server."
            )
        log = tempfile.NamedTemporaryFile(
            mode="w", prefix="ccwalk-app-", suffix=".log", delete=False
        )
        self._log_path = Path(log.name)
        self.proc = subprocess.Popen(
            self.start_command,
            shell=True,
            start_new_session=True,  # own process group so teardown kills children too
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except Exception:
            self.pgid = None
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                tail = self._output_tail()
                code = self.proc.returncode
                self.__exit__(RuntimeError, None, None)  # sweep surviving children; keep log
                raise RuntimeError(
                    f"start_command exited early (code {code}): "
                    f"{self.start_command}{tail}"
                )
            if app_ready(self.base_url, self.ready_path, timeout_s=2).get("reachable"):
                return self
            time.sleep(0.5)
        tail = self._output_tail()
        self.__exit__(RuntimeError, None, None)
        raise RuntimeError(
            f"App did not become ready at {self.base_url}{self.ready_path} "
            f"within {self.timeout_s}s (command: {self.start_command}){tail}"
        )

    def _group_alive(self) -> bool:
        if self.pgid is None:
            return False
        try:
            os.killpg(self.pgid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except Exception:
            return False

    def __exit__(self, exc_type, exc, tb) -> None:
        import signal

        try:
            if self.pgid is not None:
                try:
                    os.killpg(self.pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if self.proc is not None:
                    try:
                        self.proc.wait(timeout=10)
                    except Exception:
                        pass
                # The shell exiting proves nothing about its children:
                # sweep the whole group unconditionally if anything is left.
                deadline = time.monotonic() + 5
                while self._group_alive() and time.monotonic() < deadline:
                    time.sleep(0.2)
                if self._group_alive():
                    try:
                        os.killpg(self.pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        finally:
            if self._log_path is not None and exc_type is None:
                try:
                    self._log_path.unlink(missing_ok=True)
                except OSError:
                    pass
