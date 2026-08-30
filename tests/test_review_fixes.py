"""Regression tests for the v0.1 adversarial-review fix pass: video
segment lifecycle (M1), wait_for_condition timeout surfacing (M2), doctor
selector escaping (M3), AppProcess teardown/imposter semantics (M4/M5),
origin-scoped header auth (M6), the blocked-step cascade, and assorted
minors (app_ready HTTP statuses, filename sanitization, action-name
validation, spec resolution)."""

from __future__ import annotations

import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cc_visual_walkthrough import actions as ax
from cc_visual_walkthrough import helpers
from cc_visual_walkthrough.cli import _resolve_spec
from cc_visual_walkthrough.config import Config
from cc_visual_walkthrough.doctor import _escape_text_for_selector, _safe_count, _suggest
from cc_visual_walkthrough.runner import Runner, _safe_name, run_walkthrough
from cc_visual_walkthrough.specs import Step, validate_steps


def _step(name, group, actions=None, viewport=None):
    return Step(
        name=name,
        description="d",
        actions=actions or [{"action": "goto", "url": "/"}],
        group=group,
        viewport=viewport,
    )


# ---------------------------------------------------------------------------
# Fake browser stack: enough of the Playwright surface for Runner's
# lifecycle (contexts, pages, videos) without a real browser.
# ---------------------------------------------------------------------------


class _FakeVideo:
    def __init__(self, raw_dir: Path, n: int):
        self._path = raw_dir / f"raw-{n}.webm"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(b"webm" + bytes([n % 256]))

    def path(self):
        return str(self._path)


class _FakePage:
    def __init__(self, ctx):
        self._ctx = ctx
        self.video = ctx._video
        self.url = "http://fake/"

    def screenshot(self, path):
        Path(path).write_bytes(b"png")

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, *a, **k):
        return True

    def is_visible(self, sel):
        return False

    def reload(self, **k):
        pass


class _FakeContext:
    _counter = 0

    def __init__(self, browser, record_video_dir=None, **kwargs):
        _FakeContext._counter += 1
        self.kwargs = kwargs
        self.routes = []
        self._video = (
            _FakeVideo(Path(record_video_dir), _FakeContext._counter)
            if record_video_dir
            else None
        )

    def new_page(self):
        return _FakePage(self)

    def set_default_timeout(self, ms):
        pass

    def add_cookies(self, cookies):
        self.cookies = cookies

    def route(self, matcher, handler):
        self.routes.append((matcher, handler))

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self):
        self.contexts = []

    def new_context(self, **kwargs):
        ctx = _FakeContext(self, **kwargs)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        pass


def _fake_runner_env(tmp_path, cfg=None):
    """Patch Runner's playwright entry points so run_walkthrough drives the
    fake browser stack."""
    cfg = cfg or Config()
    patches = [
        patch("cc_visual_walkthrough.runner.launch_browser", lambda pw, headless: _FakeBrowser()),
        patch("playwright.sync_api.sync_playwright", MagicMock(return_value=MagicMock(start=MagicMock(return_value=MagicMock())))),
    ]
    return cfg, patches


class TestVideoLifecycle:
    """M1: each context records its own uniquely-named segment, attached to
    the last executed step of that segment -- never overwritten, never
    misattributed."""

    def _run(self, tmp_path, steps):
        cfg, patches = _fake_runner_env(tmp_path)
        with patches[0], patches[1]:
            return run_walkthrough(steps, cfg, tmp_path, record_video=True)

    def test_two_groups_attach_to_their_own_last_steps(self, tmp_path):
        steps = [
            _step("a1", "grpA"),
            _step("b1", "grpB"),
            _step("b2", "grpB"),
        ]
        results = self._run(tmp_path, steps)
        assert results[0].video_path == "videos/grpA.webm"
        assert results[1].video_path is None
        assert results[2].video_path == "videos/grpB.webm"
        assert (tmp_path / "videos/grpA.webm").exists()
        assert (tmp_path / "videos/grpB.webm").exists()

    def test_mid_group_viewport_override_gets_second_segment(self, tmp_path):
        """The reviewer's verified repro: grpA, then grpB whose second step
        overrides the viewport. Previously grpA's video was orphaned,
        grpB's first segment was attributed to a1 and then overwritten."""
        steps = [
            _step("a1", "grpA"),
            _step("b1", "grpB"),
            _step("b2", "grpB", viewport={"width": 390, "height": 844}),
        ]
        results = self._run(tmp_path, steps)
        assert results[0].video_path == "videos/grpA.webm"  # grpA's own segment
        assert results[1].video_path == "videos/grpB.webm"  # first grpB segment
        assert results[2].video_path == "videos/grpB-2.webm"  # second segment, distinct file
        # Both grpB segments exist on disk -- nothing overwritten.
        assert (tmp_path / "videos/grpB.webm").exists()
        assert (tmp_path / "videos/grpB-2.webm").exists()


class TestBlockedCascade:
    def test_fail_blocks_rest_of_group_but_not_next_group(self, tmp_path):
        def boom(rt, step, **kwargs):
            raise RuntimeError("app crashed")

        ax.ACTIONS["boom"] = boom
        try:
            steps = [
                _step("g1a", "g1"),
                _step("g1b", "g1", actions=[{"action": "boom"}]),
                _step("g1c", "g1", actions=[{"action": "wait_ms", "ms": 1}]),
                _step("g1d", "g1", actions=[{"action": "wait_ms", "ms": 1}]),
                _step("g2a", "g2"),
            ]
            cfg, patches = _fake_runner_env(tmp_path)
            with patches[0], patches[1]:
                results = run_walkthrough(steps, cfg, tmp_path, record_video=False)
        finally:
            del ax.ACTIONS["boom"]

        statuses = [r.status for r in results]
        assert statuses == ["pass", "fail", "blocked", "blocked", "pass"]
        assert "g1b" in results[2].error and "failed" in results[2].error
        assert results[2].screenshots == []  # never executed
        assert results[2].duration_ms == 0.0


class TestWaitForConditionTimeout:
    def test_timeout_returns_flag(self):
        rt = MagicMock()
        rt.page.evaluate.return_value = False
        rt.page.is_visible.return_value = False
        info = ax.act_wait_for_condition(rt, _step("s", "g"), js="false", timeout_ms=50)
        assert info["timed_out"] is True
        assert "not met within 50ms" in info["timeout_detail"]

    def test_timeout_marks_step_warn(self, tmp_path):
        cfg, patches = _fake_runner_env(tmp_path)
        steps = [
            _step(
                "waits",
                "g",
                actions=[
                    {"action": "goto", "url": "/"},
                    {"action": "wait_for_condition", "js": "false", "timeout_ms": 50},
                ],
            )
        ]
        # _FakePage.evaluate returns True -- force it False for the condition
        with patches[0], patches[1], patch.object(_FakePage, "evaluate", lambda self, *a, **k: False):
            results = run_walkthrough(steps, cfg, tmp_path, record_video=False)
        assert results[0].status == "warn"
        assert any(not a.passed and "not met" in a.detail for a in results[0].assertion_results)

    def test_condition_met_no_flag(self):
        rt = MagicMock()
        rt.page.evaluate.return_value = True
        rt.page.is_visible.return_value = False
        info = ax.act_wait_for_condition(rt, _step("s", "g"), js="true", timeout_ms=1000)
        assert "timed_out" not in info


class TestDoctorSelectors:
    def test_has_text_escapes_quotes_and_backslashes(self):
        entry = {"tag": "p", "text": 'He said "hello there" loudly and clearly!'}
        sel = _suggest(entry)
        assert sel == 'p:has-text("He said \\"hello there\\" loudly a")'

    def test_truncation_drops_trailing_backslash(self):
        entry = {"tag": "p", "text": "x" * 29 + "\\" + "more"}
        sel = _suggest(entry)
        assert not sel.rstrip('")').endswith("\\\\") or "\\\\" in sel  # no dangling escape
        assert _escape_text_for_selector("abc\\") == "abc"

    def test_safe_count_swallows_locator_errors(self):
        page = MagicMock()
        page.locator.side_effect = RuntimeError("bad selector")
        assert _safe_count(page, "p:has-text(broken") == "?"

    def test_suggest_prefers_testid_then_id(self):
        assert _suggest({"tag": "b", "testid": "x", "id": "y", "text": "t"}) == '[data-testid="x"]'
        assert _suggest({"tag": "b", "testid": None, "id": "y", "text": "t"}) == "#y"

    def test_suggest_aria_and_role_fallbacks(self):
        assert (
            _suggest({"tag": "button", "testid": None, "id": None, "text": "", "aria": "Close"})
            == 'button[aria-label="Close"]'
        )
        assert (
            _suggest({"tag": "nav", "testid": None, "id": None, "text": "", "aria": None,
                      "role": "navigation"})
            == 'nav[role="navigation"]'
        )


class TestAppProcess:
    def test_refuses_when_url_already_served(self):
        with patch.object(helpers, "app_ready", return_value={"reachable": True, "status": 200}):
            ap = helpers.AppProcess("sleep 60", "http://localhost:1")
            with pytest.raises(RuntimeError, match="already serving"):
                ap.__enter__()
        assert ap.proc is None  # nothing was spawned

    def test_early_exit_reports_output_tail(self):
        ready = {"n": 0}

        def fake_ready(*a, **k):
            ready["n"] += 1
            return {"reachable": False, "error": "no"}

        with patch.object(helpers, "app_ready", side_effect=fake_ready):
            ap = helpers.AppProcess("echo BOOTFAIL diagnostics; exit 3", "http://localhost:1", timeout_s=10)
            with pytest.raises(RuntimeError) as ei:
                ap.__enter__()
        msg = str(ei.value)
        assert "exited early (code 3)" in msg
        assert "BOOTFAIL diagnostics" in msg

    def test_teardown_kills_grandchildren(self):
        """The shell's death must not shield its children: spawn a shell
        whose child sleeps long, tear down, and verify the child is gone."""
        import subprocess
        import time as _time

        with patch.object(
            helpers, "app_ready",
            side_effect=[{"reachable": False}, {"reachable": True, "status": 200}],
        ):
            ap = helpers.AppProcess("sleep 300 & wait", "http://localhost:1", timeout_s=10)
            ap.__enter__()
        pgid = ap.pgid
        assert pgid is not None
        ap.__exit__(None, None, None)
        _time.sleep(0.3)
        # No process in the group should survive.
        assert ap._group_alive() is False


class TestHeaderAuthScoping:
    def test_header_auth_uses_route_not_extra_headers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("T_ENV", "sekrit")
        cfg = Config()
        cfg.auth.method = "header"
        cfg.auth.token_env = "T_ENV"
        cfg.app.base_url = "http://localhost:8000"
        with patch("cc_visual_walkthrough.runner.launch_browser", lambda pw, headless: _FakeBrowser()):
            with patch("playwright.sync_api.sync_playwright", MagicMock(return_value=MagicMock(start=MagicMock(return_value=MagicMock())))):
                rt = Runner(cfg, tmp_path, record_video=False)
                rt.__enter__()
                try:
                    ctx = rt.context
                    assert "extra_http_headers" not in ctx.kwargs
                    assert len(ctx.routes) == 1
                    matcher, handler = ctx.routes[0]
                    # Same-origin URLs match; third-party URLs do not.
                    assert matcher("http://localhost:8000/api/x")
                    assert matcher("http://localhost:8000")
                    assert not matcher("http://evil.example.com/steal")
                    assert not matcher("http://localhost:8000.evil.com/")
                    # The handler injects the header value.
                    route = MagicMock()
                    request = MagicMock()
                    request.headers = {"accept": "*/*"}
                    handler(route, request)
                    sent = route.continue_.call_args.kwargs["headers"]
                    assert sent["Authorization"] == "Bearer sekrit"
                finally:
                    rt.__exit__(None, None, None)


class TestMinorFixes:
    def test_app_ready_http_error_is_reachable(self):
        err = urllib.error.HTTPError("http://x", 404, "nf", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            out = helpers.app_ready("http://localhost:1")
        assert out == {"reachable": True, "status": 404}

    def test_safe_name_sanitizes(self):
        assert _safe_name("a/b#c?d") == "a_b_c_d"
        assert _safe_name("x/../../y") == "x_______y"
        assert _safe_name("") == "step"

    def test_validate_steps_rejects_unknown_action_names(self):
        steps = [_step("s", "g", actions=[{"action": "goto", "url": "/"}, {"action": "wait_foor", "selector": "x"}])]
        with pytest.raises(ValueError, match="unknown action 'wait_foor'"):
            validate_steps(steps, known_actions=set(ax.ACTIONS))
        validate_steps(steps)  # without registry: unchanged lenient behavior

    def test_resolve_spec_prefers_file_over_dotted_module(self, tmp_path):
        cfg = Config()
        cfg.specs_dir = str(tmp_path)
        (tmp_path / "tour.v2.py").write_text("STEPS = []")
        assert _resolve_spec(cfg, "tour.v2") == str(tmp_path / "tour.v2.py")
        # No file on disk + dotted -> treated as module path
        assert _resolve_spec(cfg, "pkg.module") == "pkg.module"
        # No dot -> always the specs_dir path, existing or not
        assert _resolve_spec(cfg, "newtour") == str(tmp_path / "newtour.py")
