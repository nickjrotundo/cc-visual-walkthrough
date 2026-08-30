"""Action dispatch, wait_for_condition semantics, assertion evaluation,
auth strategies, browser fallback, custom-actions loading, and CLI
parsing. All Playwright interaction is mocked -- no browser launches."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from cc_visual_walkthrough import actions as ax
from cc_visual_walkthrough import browser
from cc_visual_walkthrough.cli import _resolve_spec, build_arg_parser
from cc_visual_walkthrough.config import Config
from cc_visual_walkthrough.helpers import app_ready
from cc_visual_walkthrough.runner import Runner, evaluate_assertions
from cc_visual_walkthrough.specs import Assertion, Step


def _step(name="s1", actions=None, group="misc"):
    return Step(
        name=name,
        description="desc",
        actions=actions or [{"action": "goto", "url": "/"}],
        group=group,
    )


def _mock_runner():
    """Loose MagicMock standing in for Runner -- the action functions only
    touch a handful of attributes/methods."""
    rt = MagicMock()
    rt.page = MagicMock()
    rt.base_url = "http://localhost:8000"
    rt.session_ids = {}
    return rt


class TestActionDispatch:
    def test_run_action_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown action"):
            ax.run_action(_mock_runner(), _step(), {"action": "does_not_exist"})

    def test_click_dispatches_to_page_click(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "click", "selector": "#btn"})
        rt.page.click.assert_called_once_with("#btn", timeout=10000)

    def test_fill_dispatches_to_page_fill(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "fill", "selector": "#in", "value": "hello"})
        rt.page.fill.assert_called_once_with("#in", "hello")

    def test_press_hover_select_upload(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "press", "selector": "#in", "key": "Enter"})
        rt.page.press.assert_called_once_with("#in", "Enter")
        ax.run_action(rt, _step(), {"action": "hover", "selector": "#menu"})
        rt.page.hover.assert_called_once_with("#menu")
        ax.run_action(rt, _step(), {"action": "select_option", "selector": "#sel", "value": "a"})
        rt.page.select_option.assert_called_once_with("#sel", value="a")
        ax.run_action(rt, _step(), {"action": "upload_file", "selector": "#f", "path": "/tmp/x"})
        rt.page.set_input_files.assert_called_once_with("#f", "/tmp/x")

    def test_select_option_by_label(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "select_option", "selector": "#sel", "label": "Two"})
        rt.page.select_option.assert_called_once_with("#sel", label="Two")

    def test_goto_relative_path_prefixes_base_url_and_applies_auth(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "goto", "url": "/dash"})
        rt.ensure_pre_goto_auth.assert_called_once()
        rt.page.goto.assert_called_once_with(
            "http://localhost:8000/dash", wait_until="domcontentloaded"
        )
        rt.ensure_post_goto_auth.assert_called_once()

    def test_goto_absolute_url_passed_through(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "goto", "url": "https://example.com/x"})
        rt.page.goto.assert_called_once_with(
            "https://example.com/x", wait_until="domcontentloaded"
        )

    def test_goto_apply_auth_false_skips_auth_hooks(self):
        rt = _mock_runner()
        ax.run_action(rt, _step(), {"action": "goto", "url": "/login", "apply_auth": False})
        rt.ensure_pre_goto_auth.assert_not_called()
        rt.ensure_post_goto_auth.assert_not_called()

    def test_login_form_delegates_to_runner(self):
        rt = _mock_runner()
        info = ax.run_action(rt, _step(), {"action": "login_form"})
        rt.perform_form_login.assert_called_once()
        assert info == {"logged_in": True}

    def test_override_session_calls_runner_helper(self):
        rt = _mock_runner()
        rt.override_session_id.return_value = "ccwalk-foo-123"
        info = ax.run_action(rt, _step(), {"action": "override_session", "logical_name": "foo"})
        rt.override_session_id.assert_called_once_with("foo")
        assert info == {"session_id": "ccwalk-foo-123"}

    def test_mock_route_registers_handler_returning_json(self):
        rt = _mock_runner()
        ax.run_action(
            rt, _step(), {"action": "mock_route", "url_pattern": "**/x", "json_body": {"a": 1}}
        )
        rt.page.route.assert_called_once()
        pattern, handler = rt.page.route.call_args[0]
        assert pattern == "**/x"
        fake_route = MagicMock()
        handler(fake_route)
        _, kwargs = fake_route.fulfill.call_args
        assert json.loads(kwargs["body"]) == {"a": 1}


class TestWaitForCondition:
    """Generalized from the predecessor's wait_for_response, whose three
    live-run bugs (spin-on-fast-reply, break-too-early, removed DOM
    signal) shaped these semantics: the js condition is authoritative,
    the progress selector only paces screenshots."""

    def test_returns_immediately_when_condition_already_true(self):
        rt = _mock_runner()
        rt.page.is_visible.return_value = False
        rt.page.evaluate.side_effect = [True]
        result = ax.act_wait_for_condition(
            rt, _step(), js="window.done === true", timeout_ms=90000,
            capture_progress=True, progress_selector="#spin",
        )
        assert result["saw_progress"] is False
        assert rt.page.evaluate.call_count == 1

    def test_keeps_waiting_while_condition_false_even_if_progress_gone(self):
        rt = _mock_runner()
        rt.page.is_visible.side_effect = [True, False, False]
        rt.page.evaluate.side_effect = [False, False, True]
        result = ax.act_wait_for_condition(
            rt, _step(), js="window.done", timeout_ms=90000,
            capture_progress=False, progress_selector="#spin",
        )
        assert result["saw_progress"] is True
        assert rt.page.evaluate.call_count == 3

    def test_captures_progress_screenshot_while_progress_visible(self):
        rt = _mock_runner()
        rt.page.is_visible.side_effect = [True, False]
        rt.page.evaluate.side_effect = [False, True]
        rt.screenshot.return_value = "shot.png"
        result = ax.act_wait_for_condition(
            rt, _step(), js="window.done", timeout_ms=90000,
            capture_progress=True, poll_interval_ms=0, progress_selector="#spin",
        )
        assert result["progress_screenshots"] == ["shot.png"]

    def test_no_progress_selector_never_screenshots(self):
        rt = _mock_runner()
        rt.page.evaluate.side_effect = [False, True]
        result = ax.act_wait_for_condition(
            rt, _step(), js="window.done", timeout_ms=90000, capture_progress=True,
        )
        assert result["progress_screenshots"] == []
        rt.page.is_visible.assert_not_called()


class TestEvaluateAssertions:
    def test_visibility_check_pass(self):
        page = MagicMock()
        page.wait_for_selector.return_value = None
        results = evaluate_assertions(page, [Assertion(selector="#x", description="x visible")])
        assert results[0].passed is True
        page.wait_for_selector.assert_called_once_with("#x", timeout=5000, state="visible")

    def test_visibility_check_fail_on_timeout(self):
        page = MagicMock()
        page.wait_for_selector.side_effect = TimeoutError("nope")
        results = evaluate_assertions(page, [Assertion(selector="#x")])
        assert results[0].passed is False
        assert "TimeoutError" in results[0].detail

    def test_min_count_pass_and_fail(self):
        page = MagicMock()
        locator = MagicMock()
        locator.count.return_value = 3
        page.locator.return_value = locator
        results = evaluate_assertions(
            page,
            [
                Assertion(selector=".row", min_count=2, description="enough", timeout_ms=200),
                Assertion(selector=".row", min_count=5, description="too many", timeout_ms=200),
            ],
        )
        assert results[0].passed is True
        assert results[1].passed is False

    def test_text_contains_case_insensitive(self):
        page = MagicMock()
        first = MagicMock()
        first.input_value.side_effect = Exception("not a form element")
        first.text_content.return_value = "Hello Jim Halpert"
        page.locator.return_value.first = first
        results = evaluate_assertions(
            page, [Assertion(selector="#msg", text_contains="jim")]
        )
        assert results[0].passed is True

    def test_text_contains_reads_input_value_for_form_elements(self):
        """Regression: an <input>'s content lives in .value, not
        .textContent (always empty) -- found live in the predecessor."""
        page = MagicMock()
        first = MagicMock()
        first.input_value.return_value = "Nick Rotundo"
        page.locator.return_value.first = first
        results = evaluate_assertions(
            page, [Assertion(selector="#name", text_contains="Nick")]
        )
        assert results[0].passed is True
        first.text_content.assert_not_called()


class TestRunnerAuth:
    def _cfg_form(self) -> Config:
        cfg = Config()
        cfg.auth.method = "form"
        cfg.auth.login_path = "/login"
        cfg.auth.username_selector = "#u"
        cfg.auth.password_selector = "#p"
        cfg.auth.submit_selector = "#go"
        cfg.auth.success_selector = "#dash"
        cfg.auth.username_env = "T_USER"
        cfg.auth.password_env = "T_PASS"
        return cfg

    def _bare_runner(self, cfg: Config, tmp_path) -> Runner:
        rt = Runner(cfg, tmp_path)  # no __enter__: no browser
        rt.page = MagicMock()
        return rt

    def test_perform_form_login_flow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("T_USER", "alice")
        monkeypatch.setenv("T_PASS", "s3cret")
        rt = self._bare_runner(self._cfg_form(), tmp_path)
        rt.perform_form_login()
        rt.page.goto.assert_called_once_with(
            "http://localhost:8000/login", wait_until="domcontentloaded"
        )
        rt.page.fill.assert_any_call("#u", "alice")
        rt.page.fill.assert_any_call("#p", "s3cret")
        rt.page.click.assert_called_once_with("#go")
        rt.page.wait_for_selector.assert_called_once_with("#dash", state="visible")
        assert rt._auth_applied is True

    def test_perform_form_login_without_credentials_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("T_USER", raising=False)
        monkeypatch.delenv("T_PASS", raising=False)
        rt = self._bare_runner(self._cfg_form(), tmp_path)
        with pytest.raises(ValueError, match="TEST account"):
            rt.perform_form_login()

    def test_localstorage_injection_on_post_goto(self, tmp_path, monkeypatch):
        monkeypatch.setenv("T_TOKEN", "tok123")
        cfg = Config()
        cfg.auth.method = "localstorage"
        cfg.auth.ls_key = "api_token"
        cfg.auth.token_env = "T_TOKEN"
        cfg.auth.ls_extra_items = {"user_id": "7"}
        rt = self._bare_runner(cfg, tmp_path)
        rt.ensure_post_goto_auth()
        assert rt.page.evaluate.call_count == 2
        rt.page.reload.assert_called_once_with(wait_until="domcontentloaded")
        assert rt._auth_applied is True
        # Second call is a no-op.
        rt.ensure_post_goto_auth()
        assert rt.page.evaluate.call_count == 2

    def test_override_session_requires_isolation_enabled(self, tmp_path):
        rt = self._bare_runner(Config(), tmp_path)
        with pytest.raises(ValueError, match="session_isolation"):
            rt.override_session_id("x")

    def test_override_session_uses_configured_prefix(self, tmp_path):
        cfg = Config()
        cfg.session_isolation.enabled = True
        cfg.session_isolation.prefix = "tour-"
        rt = self._bare_runner(cfg, tmp_path)
        sid = rt.override_session_id("smoke")
        assert sid.startswith("tour-smoke-")
        rt.page.evaluate.assert_called_once()
        assert rt.session_ids["smoke"] == sid


class TestLaunchBrowserFallback:
    def test_falls_back_to_system_chromium_when_default_launch_fails(self, monkeypatch):
        monkeypatch.setattr(browser, "_FALLBACK_CHROMIUM_PATHS", ["/fake/chromium"])
        monkeypatch.setattr(browser.Path, "exists", lambda self: str(self) == "/fake/chromium")
        pw = MagicMock()
        pw.chromium.launch.side_effect = [Exception("missing libs"), "browser-instance"]
        result = browser.launch_browser(pw, headless=True)
        assert result == "browser-instance"
        _, kwargs = pw.chromium.launch.call_args
        assert kwargs["executable_path"] == "/fake/chromium"

    def test_raises_when_no_fallback_available(self, monkeypatch):
        monkeypatch.setattr(browser, "_FALLBACK_CHROMIUM_PATHS", [])
        pw = MagicMock()
        pw.chromium.launch.side_effect = Exception("missing libs")
        with pytest.raises(RuntimeError, match="Could not launch"):
            browser.launch_browser(pw, headless=True)

    def test_uses_default_launch_when_it_succeeds(self):
        pw = MagicMock()
        pw.chromium.launch.return_value = "ok-browser"
        assert browser.launch_browser(pw, headless=True) == "ok-browser"
        pw.chromium.launch.assert_called_once_with(headless=True)


class TestAppReady:
    def test_probes_configured_path(self, monkeypatch):
        captured: list[str] = []

        class _FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=5):
            captured.append(req.full_url)
            return _FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = app_ready("http://localhost:8000", "/healthz")
        assert result == {"reachable": True, "status": 200}
        assert captured == ["http://localhost:8000/healthz"]

    def test_unreachable_reports_error(self, monkeypatch):
        def fake_urlopen(req, timeout=5):
            raise OSError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = app_ready("http://localhost:1", "/")
        assert result["reachable"] is False
        assert "refused" in result["error"]


class TestCustomActions:
    def test_load_and_register(self, tmp_path):
        mod = tmp_path / "extra.py"
        mod.write_text(
            "def act_shout(rt, step, text, **_):\n"
            "    return {'shout': text.upper()}\n\n"
            "def register(actions):\n"
            "    actions['shout'] = act_shout\n"
        )
        added = ax.load_custom_actions(mod)
        try:
            assert added == ["shout"]
            info = ax.run_action(_mock_runner(), _step(), {"action": "shout", "text": "hi"})
            assert info == {"shout": "HI"}
        finally:
            ax.ACTIONS.pop("shout", None)

    def test_module_without_register_rejected(self, tmp_path):
        mod = tmp_path / "bad.py"
        mod.write_text("X = 1\n")
        with pytest.raises(ValueError, match="register"):
            ax.load_custom_actions(mod)

    def test_missing_module_rejected(self):
        with pytest.raises(ValueError, match="not found"):
            ax.load_custom_actions("nope/missing.py")


class TestCli:
    def test_run_defaults(self):
        args = build_arg_parser().parse_args(["run"])
        assert args.command == "run"
        assert args.spec is None
        assert args.headed is False
        assert args.no_video is False
        assert args.embed is False
        assert args.mp4 is False
        assert args.start_app is False
        assert args.capture_only is None

    def test_run_capture_only_with_viewports(self):
        args = build_arg_parser().parse_args(
            ["run", "--capture-only", "/admin", "--viewports", "390,768"]
        )
        assert args.capture_only == "/admin"
        assert args.viewports == "390,768"

    def test_doctor_and_report_subcommands_parse(self):
        d = build_arg_parser().parse_args(["doctor", "/page", "--find", "Submit"])
        assert d.command == "doctor" and d.url == "/page" and d.find == "Submit"
        r = build_arg_parser().parse_args(["report", "reports/x", "--embed"])
        assert r.command == "report" and r.run_dir == "reports/x" and r.embed is True

    def test_resolve_spec_bare_name_uses_specs_dir(self):
        cfg = Config()
        cfg.specs_dir = "tours"
        assert _resolve_spec(cfg, "main") == "tours/main.py"
        assert _resolve_spec(cfg, None) == "tours/core_tour.py"
        assert _resolve_spec(cfg, "pkg.module") == "pkg.module"
        assert _resolve_spec(cfg, "demo/tour.py") == "demo/tour.py"
