"""Tests for `ccwalk serve`: runs index, HTTP routes/headers, pidfile."""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from cc_visual_walkthrough import serve


def _mk_run(out_root: Path, run_id: str, statuses: list[str] | None = None,
            spec: str = "walkthrough/specs/core_tour.py", meta: bool = True,
            report: bool = True, git_head: str = "abc1234") -> Path:
    d = out_root / run_id
    d.mkdir(parents=True)
    if report:
        (d / "report.html").write_text("<html>report</html>")
    if meta:
        results = [
            {"name": f"s{i}", "status": s, "duration_ms": 100.0}
            for i, s in enumerate(statuses or [])
        ]
        (d / "run_meta.json").write_text(json.dumps(
            {"spec": spec, "git_head": git_head, "results": results}
        ))
    return d


# -- scan_runs / index rendering -------------------------------------------


def test_scan_runs_sorts_newest_first_with_counts(tmp_path):
    _mk_run(tmp_path, "20260828-000000", ["pass", "pass"])
    _mk_run(tmp_path, "20260830-120000", ["pass", "warn", "fail", "blocked"])
    _mk_run(tmp_path, "20260829-050000", ["pass"])
    rows = serve.scan_runs(tmp_path)
    assert [r.run_id for r in rows] == [
        "20260830-120000", "20260829-050000", "20260828-000000"
    ]
    top = rows[0]
    assert top.ok and top.total == 4
    assert top.counts == {"pass": 1, "warn": 1, "fail": 1, "blocked": 1}
    assert top.duration_ms == pytest.approx(400.0)
    assert top.git_head == "abc1234"


def test_scan_runs_unreadable_meta_and_missing_meta(tmp_path):
    d = _mk_run(tmp_path, "20260830-000001", meta=False)
    (d / "run_meta.json").write_text("{not json")
    rows = serve.scan_runs(tmp_path)
    assert len(rows) == 1 and rows[0].ok is False


def test_index_html_rows_links_escaping(tmp_path):
    _mk_run(tmp_path, "20260830-120000", ["pass", "pass"],
            spec='<script>alert(1)</script>')
    bad = _mk_run(tmp_path, "20260829-000000", meta=False)
    (bad / "run_meta.json").write_text("nope")
    html = serve.render_index_html(serve.scan_runs(tmp_path), app_name="My <App>")
    assert '<a href="/20260830-120000/report.html">' in html
    assert "2/2 passed" in html
    assert "(unreadable)" in html
    assert "<script>alert(1)</script>" not in html  # escaped
    assert "My <App>" not in html and "My &lt;App&gt;" in html


def test_index_html_no_runs(tmp_path):
    html = serve.render_index_html(serve.scan_runs(tmp_path))
    assert "No runs yet" in html and "ccwalk run" in html


# -- HTTP server ------------------------------------------------------------


@pytest.fixture()
def live_server(tmp_path):
    _mk_run(tmp_path, "20260830-120000", ["pass", "warn"])
    httpd = serve.make_server(tmp_path, app_name="Demo", port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url: str):
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_server_index_report_404_all_no_store(live_server):
    _root, base = live_server
    code, headers, body = _get(base + "/")
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert b"20260830-120000" in body and b"1/2 passed" in body

    code, headers, _ = _get(base + "/20260830-120000/report.html")
    assert code == 200 and headers["Cache-Control"] == "no-store"

    code, headers, _ = _get(base + "/nope/report.html")
    assert code == 404 and headers["Cache-Control"] == "no-store"


def test_server_containment(live_server):
    _root, base = live_server
    code, _, _ = _get(base + "/../../../etc/passwd")
    assert code == 404
    code, _, _ = _get(base + "/%2e%2e/%2e%2e/etc/passwd")
    assert code == 404


# -- pidfile lifecycle -------------------------------------------------------


def test_daemon_status_stale_dead_pid(tmp_path):
    serve.write_pidfile(tmp_path, pid=99999999, port=1234, bind="127.0.0.1")
    assert serve.daemon_status(tmp_path) is None
    assert not (tmp_path / ".ccwalk" / "serve.pid").exists()


def test_daemon_status_foreign_live_pid_not_killed(tmp_path):
    proc = subprocess.Popen(["sleep", "5"])
    try:
        serve.write_pidfile(tmp_path, pid=proc.pid, port=1234, bind="127.0.0.1")
        # A live pid that isn't a ccwalk process is stale, and stop() must
        # not touch it.
        assert serve.daemon_status(tmp_path) is None
        assert serve.stop(tmp_path) == 0
        assert proc.poll() is None  # still alive
    finally:
        proc.kill()
        proc.wait()


def test_daemon_start_stop_lifecycle(tmp_path):
    out_root = tmp_path / "reports" / "walkthrough"
    _mk_run(out_root, "20260830-120000", ["pass"])
    rc = serve.start(tmp_path, out_root, app_name="Demo", port=0, daemon=True)
    assert rc == 0
    info = serve.daemon_status(tmp_path)
    assert info is not None
    code, headers, body = _get(f"http://127.0.0.1:{info['port']}/")
    assert code == 200 and b"20260830-120000" in body
    assert headers["Cache-Control"] == "no-store"

    # restart-on-start replaces the running server
    rc = serve.start(tmp_path, out_root, app_name="Demo", port=0, daemon=True)
    assert rc == 0
    info2 = serve.daemon_status(tmp_path)
    assert info2 is not None and info2["pid"] != info["pid"]

    assert serve.stop(tmp_path) == 0
    assert serve.daemon_status(tmp_path) is None
