"""Action registry: the verbs a spec's action dicts can use.

Every action takes the live ``Runner`` (``rt``), the current ``Step``, and
its own kwargs, and returns an info dict merged into the step's log
(``screenshot`` / ``progress_screenshots`` keys are collected into the
report). The registry is a plain dict, so app-specific actions can be
added from a custom module -- see ``load_custom_actions``.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Callable

from .specs import Step


def _url_for(rt, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return rt.base_url + path


def act_goto(rt, step: Step, url: str, apply_auth: bool = True, **_) -> dict:
    """Navigate. On the first goto of a fresh browser context this also
    establishes auth per the config (form login / localStorage injection);
    cookie and header auth are applied at context creation instead."""
    if apply_auth:
        rt.ensure_pre_goto_auth()
    rt.page.goto(_url_for(rt, url), wait_until="domcontentloaded")
    if apply_auth:
        rt.ensure_post_goto_auth()
    return {}


def act_reload(rt, step: Step, **_) -> dict:
    rt.page.reload(wait_until="domcontentloaded")
    return {}


def act_click(rt, step: Step, selector: str, timeout_ms: int = 10000, **_) -> dict:
    rt.page.click(selector, timeout=timeout_ms)
    return {}


def act_fill(rt, step: Step, selector: str, value: str, **_) -> dict:
    rt.page.fill(selector, value)
    return {}


def act_press(rt, step: Step, selector: str, key: str, **_) -> dict:
    rt.page.press(selector, key)
    return {}


def act_hover(rt, step: Step, selector: str, **_) -> dict:
    rt.page.hover(selector)
    return {}


def act_select_option(
    rt, step: Step, selector: str, value: str | None = None, label: str | None = None, **_
) -> dict:
    if label is not None:
        rt.page.select_option(selector, label=label)
    else:
        rt.page.select_option(selector, value=value)
    return {}


def act_upload_file(rt, step: Step, selector: str, path: str, **_) -> dict:
    rt.page.set_input_files(selector, path)
    return {}


def act_wait_for(
    rt, step: Step, selector: str, state: str = "visible", timeout_ms: int = 15000, **_
) -> dict:
    rt.page.wait_for_selector(selector, state=state, timeout=timeout_ms)
    return {}


def act_wait_ms(rt, step: Step, ms: int, **_) -> dict:
    rt.page.wait_for_timeout(ms)
    return {}


def act_set_viewport(rt, step: Step, width: int, height: int, **_) -> dict:
    rt.page.set_viewport_size({"width": width, "height": height})
    return {}


def act_screenshot(rt, step: Step, suffix: str = "", **_) -> dict:
    path = rt.screenshot(step, suffix=suffix)
    return {"screenshot": path}


def act_scroll_into_view(rt, step: Step, selector: str, **_) -> dict:
    rt.page.locator(selector).first.scroll_into_view_if_needed()
    return {}


def act_login_form(rt, step: Step, **_) -> dict:
    """Perform the configured form login explicitly (useful as a group's
    opening step when the login flow itself should appear in the tour)."""
    rt.perform_form_login()
    return {"logged_in": True}


def act_override_session(rt, step: Step, logical_name: str = "default", **_) -> dict:
    sid = rt.override_session_id(logical_name)
    return {"session_id": sid}


def act_wait_for_condition(
    rt,
    step: Step,
    js: str,
    timeout_ms: int = 90000,
    capture_progress: bool = False,
    poll_interval_ms: int = 2500,
    progress_selector: str = "",
    settle_ms: int = 400,
    **_,
) -> dict:
    """Poll ``js`` (a no-arg JS function body evaluated via
    ``() => (expr)``; return truthy when the wait should END) until it
    holds or ``timeout_ms`` elapses. While waiting, if
    ``progress_selector`` is visible and ``capture_progress`` is set, a
    progress screenshot is taken every ``poll_interval_ms`` -- this is how
    long async operations (spinners, progress labels, streaming
    responses) get their wait-state captured in the report.

    The internal poll granularity is finer (300ms) than
    ``poll_interval_ms`` (which only paces progress screenshots), so a
    near-instant completion is still detected promptly -- a lesson
    inherited from the predecessor system, where gating on a
    spinner-visible->hidden transition spun for the full timeout on
    fast replies (see DESIGN.md).
    """
    shots: list[str] = []
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    saw_progress = False
    met = False
    last_shot_at = 0.0
    check_interval_ms = min(300, poll_interval_ms) if poll_interval_ms else 300
    expr = f"() => ({js})"
    while time.monotonic() < deadline:
        if progress_selector and rt.page.is_visible(progress_selector):
            saw_progress = True
            now = time.monotonic()
            if capture_progress and (now - last_shot_at) * 1000 >= poll_interval_ms:
                shots.append(rt.screenshot(step, suffix=f"wait_{len(shots)}"))
                last_shot_at = now
        if rt.page.evaluate(expr):
            met = True
            break
        rt.page.wait_for_timeout(check_interval_ms)
    if not met and rt.page.evaluate(expr):
        met = True  # condition became true exactly at the deadline
    if not met:
        # A timed-out evidence wait must be VISIBLE: the runner turns this
        # into a failed pseudo-assertion (step status warn), never a
        # silent PASS.
        return {
            "progress_screenshots": shots,
            "saw_progress": saw_progress,
            "timed_out": True,
            "timeout_detail": f"wait_for_condition {js!r} not met within {timeout_ms}ms",
        }
    if settle_ms:
        rt.page.wait_for_timeout(settle_ms)
    return {"progress_screenshots": shots, "saw_progress": saw_progress}


def act_mock_route(rt, step: Step, url_pattern: str, json_body: Any, status: int = 200, **_) -> dict:
    """Intercept a network request with a canned JSON response (e.g. to
    stop a wizard auto-skipping itself on an already-configured backend).
    Registered on the page, so it survives a subsequent goto/reload."""
    body = json.dumps(json_body)

    def handler(route):
        route.fulfill(status=status, content_type="application/json", body=body)

    rt.page.route(url_pattern, handler)
    return {}


ACTIONS: dict[str, Callable[..., dict]] = {
    "goto": act_goto,
    "reload": act_reload,
    "click": act_click,
    "fill": act_fill,
    "press": act_press,
    "hover": act_hover,
    "select_option": act_select_option,
    "upload_file": act_upload_file,
    "wait_for": act_wait_for,
    "wait_ms": act_wait_ms,
    "set_viewport": act_set_viewport,
    "screenshot": act_screenshot,
    "scroll_into_view": act_scroll_into_view,
    "login_form": act_login_form,
    "override_session": act_override_session,
    "wait_for_condition": act_wait_for_condition,
    "mock_route": act_mock_route,
}


def run_action(rt, step: Step, action_dict: dict[str, Any]) -> dict:
    kwargs = {k: v for k, v in action_dict.items() if k != "action"}
    name = action_dict["action"]
    fn = ACTIONS.get(name)
    if fn is None:
        raise ValueError(f"Unknown action {name!r} (known: {sorted(ACTIONS)})")
    return fn(rt, step, **kwargs)


def load_custom_actions(module_path: str | Path) -> list[str]:
    """Import a custom-actions module by file path and let it register
    into ACTIONS. The module must expose ``register(actions: dict)``.
    Returns the action names it added."""
    path = Path(module_path)
    if not path.exists():
        raise ValueError(f"custom_actions module not found: {module_path}")
    spec = importlib.util.spec_from_file_location(f"ccwalk_custom_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import custom_actions module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    register = getattr(mod, "register", None)
    if not callable(register):
        raise ValueError(f"{module_path} must define register(actions: dict)")
    before = set(ACTIONS)
    register(ACTIONS)
    return sorted(set(ACTIONS) - before)
