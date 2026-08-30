"""Regression tests for the publish-readiness review findings."""
from __future__ import annotations

import json
import socket
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import patch

from cc_visual_walkthrough import __version__, serve
from cc_visual_walkthrough.config import Config
from cc_visual_walkthrough.reporters import results_from_run_meta, write_report
from cc_visual_walkthrough.runner import run_capture_only

from test_review_fixes import _fake_runner_env

REPO = Path(__file__).resolve().parent.parent


# -- version discipline ----------------------------------------------------


def test_version_matches_in_all_three_places():
    py = tomllib.loads((REPO / "pyproject.toml").read_text())
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    assert py["project"]["version"] == __version__ == plugin["version"]


# -- failed-step log survives a report re-render -----------------------------


def test_fail_log_survives_report_roundtrip(tmp_path):
    run_meta = {
        "timestamp": "20260830-120000",
        "git_head": "abc",
        "base_url": "http://x",
        "app_health": {"reachable": True},
        "spec": "s",
        "results": [
            {
                "name": "broken",
                "status": "fail",
                "duration_ms": 5.0,
                "screenshots": [],
                "video_path": None,
                "error": "TimeoutError: boom",
                "assertions": [],
                "log": ["Traceback (most recent call last):", "  boom"],
                "group": "g",
                "description": "d",
            }
        ],
    }
    results = results_from_run_meta(run_meta)
    assert results[0].log == ["Traceback (most recent call last):", "  boom"]
    write_report(run_meta, results, tmp_path)
    rewritten = json.loads((tmp_path / "run_meta.json").read_text())
    assert rewritten["results"][0]["log"] == [
        "Traceback (most recent call last):", "  boom",
    ], "re-rendering must not destroy a failed step's captured traceback"


# -- portable pid ownership check -------------------------------------------


def test_pid_is_ours_falls_back_to_ps(monkeypatch):
    def no_proc(self, *a, **k):
        raise OSError("no /proc here")

    monkeypatch.setattr(serve.Path, "read_bytes", no_proc)

    class Out:
        returncode = 0
        stdout = "/usr/bin/python -m cc_visual_walkthrough.cli serve start\n"

    monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: Out())
    assert serve._pid_is_ours(12345) is True

    class OutOther:
        returncode = 0
        stdout = "/usr/sbin/nginx\n"

    monkeypatch.setattr(serve.subprocess, "run", lambda *a, **k: OutOther())
    assert serve._pid_is_ours(12345) is False


def test_pid_is_ours_unknown_when_nothing_available(monkeypatch):
    def no_proc(self, *a, **k):
        raise OSError("no /proc")

    monkeypatch.setattr(serve.Path, "read_bytes", no_proc)

    def no_ps(*a, **k):
        raise OSError("no ps either")

    monkeypatch.setattr(serve.subprocess, "run", no_ps)
    assert serve._pid_is_ours(12345) is None


def test_daemon_status_keeps_pidfile_when_ownership_unknowable(tmp_path, monkeypatch):
    import os

    serve.write_pidfile(tmp_path, os.getpid(), 1234, "127.0.0.1")
    monkeypatch.setattr(serve, "_pid_is_ours", lambda pid: None)
    info = serve.daemon_status(tmp_path)
    assert info is not None and info.get("unverified") is True
    assert serve._pidfile(tmp_path).exists(), (
        "a live pid whose ownership cannot be verified must never be "
        "auto-cleaned - deleting the pidfile would orphan a live daemon"
    )


def test_daemon_status_cleans_provably_foreign_pid(tmp_path, monkeypatch):
    import os

    serve.write_pidfile(tmp_path, os.getpid(), 1234, "127.0.0.1")
    monkeypatch.setattr(serve, "_pid_is_ours", lambda pid: False)
    assert serve.daemon_status(tmp_path) is None
    assert not serve._pidfile(tmp_path).exists()


# -- occupied port -> clean message, exit 1 ---------------------------------


def test_serve_start_reports_occupied_port_cleanly(tmp_path, capsys):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    port = blocker.getsockname()[1]
    try:
        rc = serve.start(tmp_path, tmp_path, "app", port=port, bind="127.0.0.1")
    finally:
        blocker.close()
    assert rc == 1
    err = capsys.readouterr().err
    assert "already in use" in err and "serve status" in err
    assert "Traceback" not in err


# -- capture-only: fresh context per viewport x variant ---------------------


def test_capture_only_fresh_context_per_iteration(tmp_path):
    cfg, patches = _fake_runner_env(tmp_path)
    cfg.capture_variants = [
        {"label": "dark", "actions": [{"action": "wait_ms", "ms": 1}]}
    ]
    captured = {}
    orig_launch = patches[0]
    with patches[0], patches[1]:
        from cc_visual_walkthrough import runner as runner_mod

        # grab the browser the Runner creates so contexts can be counted
        real_launch = runner_mod.launch_browser

        def counting_launch(pw, headless):
            b = real_launch(pw, headless)
            captured["browser"] = b
            return b

        with patch(
            "cc_visual_walkthrough.runner.launch_browser", counting_launch
        ):
            results = run_capture_only(
                "/page", [(390, 844), (1440, 900)], cfg, tmp_path
            )
    assert len(results) == 4  # 2 viewports x (default + dark)
    assert all(r.status == "pass" for r in results)
    # one fresh context per iteration (plus the Runner's bootstrap context):
    n_ctx = len(captured["browser"].contexts)
    assert n_ctx >= 4, (
        f"expected a fresh browser context per viewport x variant, got {n_ctx}"
        " - a shared context lets variant side effects contaminate later"
        " captures"
    )
