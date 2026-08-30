"""The Runner owns live Playwright state for one run: browser lifecycle,
per-group context/video switching, screenshot naming, and auth
application. ``run_walkthrough`` executes a spec; ``run_capture_only``
grabs one page across viewports (and configured capture variants)."""

from __future__ import annotations

import re
import time
import traceback
from pathlib import Path
from typing import Any

from .actions import run_action
from .browser import launch_browser
from .config import Config
from .helpers import get_env
from .specs import Assertion, AssertionResult, Step, StepResult


def _safe_name(name: str) -> str:
    """Sanitize a step/group name for use in a filename: step names are
    arbitrary spec strings, and '/', '#', '?', '..' etc. would create
    subdirectories, break relative <img src> URLs, or escape out_dir."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "step"


class Runner:
    """Holds live Playwright state + output paths for one run."""

    def __init__(
        self,
        cfg: Config,
        out_dir: Path,
        headed: bool = False,
        record_video: bool = True,
    ):
        self.cfg = cfg
        self.base_url = cfg.app.base_url.rstrip("/")
        self.out_dir = out_dir
        self.shots_dir = out_dir / "screenshots"
        self.videos_dir = out_dir / "videos"
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.headed = headed
        self.record_video = record_video
        self.page_timeout_ms = cfg.capture.page_timeout_ms
        self.default_viewport = dict(cfg.capture.default_viewport)

        self._pw = None
        self.browser = None
        self.context = None
        self.page = None
        self._current_group: str | None = None
        self._current_viewport: dict[str, int] | None = None
        self._auth_applied = False
        self.session_ids: dict[str, str] = {}
        self._shot_counter = 0
        # Segments recorded per group: a group re-opened with a different
        # viewport gets group-2.webm etc., never overwriting group.webm.
        self._segment_counts: dict[str, int] = {}

    # -- lifecycle -----------------------------------------------------

    def __enter__(self) -> "Runner":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = launch_browser(self._pw, headless=not self.headed)
        # Bootstrap context, replaced by ensure_group() at the first real
        # step -- recording video for it would produce an orphan init.webm
        # of a blank page no step references.
        record_video, self.record_video = self.record_video, False
        self._open_context(viewport=self.default_viewport, group="init")
        self.record_video = record_video
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._close_context()
        finally:
            try:
                if self.browser:
                    self.browser.close()
            finally:
                if self._pw:
                    self._pw.stop()
        raw_dir = self.videos_dir / "_raw"
        if raw_dir.is_dir() and not any(raw_dir.iterdir()):
            raw_dir.rmdir()

    def _open_context(self, viewport: dict[str, int], group: str) -> None:
        self._close_context()
        kwargs: dict[str, Any] = {"viewport": viewport}
        if self.record_video:
            kwargs["record_video_dir"] = str(self.videos_dir / "_raw" / group)
            kwargs["record_video_size"] = viewport
        auth = self.cfg.auth
        self.context = self.browser.new_context(**kwargs)
        # Header auth: injected ONLY for same-origin requests via routing.
        # extra_http_headers would attach the Authorization header to every
        # request the context makes -- third-party APIs, CDNs, analytics --
        # leaking the token off-origin (Playwright's own docs warn against
        # it for auth headers).
        if auth.method == "header":
            token = get_env(auth.token_env)
            if token:
                header_name = auth.header_name
                header_value = auth.header_format.format(token=token)
                origin = self.base_url

                def _inject_auth_header(route, request):
                    route.continue_(
                        headers={**request.headers, header_name: header_value}
                    )

                self.context.route(
                    lambda url: url == origin or url.startswith(origin + "/"),
                    _inject_auth_header,
                )
        if auth.method == "cookie":
            token = get_env(auth.token_env)
            if token:
                self.context.add_cookies(
                    [{"name": auth.cookie_name, "value": token, "url": self.base_url}]
                )
        self.context.set_default_timeout(self.page_timeout_ms)
        self.page = self.context.new_page()
        self._current_group = group
        self._current_viewport = viewport
        # header/cookie auth is now in place; form/localstorage happens on
        # the context's first goto.
        self._auth_applied = auth.method in ("none", "header", "cookie")

    def _close_context(self) -> str | None:
        """Close the current context, finalize its video segment into
        videos/<group>.webm (or <group>-N.webm for the group's Nth
        segment -- a viewport override mid-group records a new segment and
        must not overwrite the first), and return that path relative to
        out_dir if a video was recorded."""
        if not self.context:
            return None
        group = self._current_group
        video_obj = self.page.video if self.page else None
        try:
            self.context.close()
        except Exception:
            pass
        finally:
            self.context = None
            self.page = None
            self._current_viewport = None

        if not (self.record_video and video_obj and group):
            return None
        try:
            raw_path = Path(video_obj.path())
        except Exception:
            return None
        if not raw_path.exists():
            return None
        import shutil

        n = self._segment_counts.get(group, 0) + 1
        self._segment_counts[group] = n
        stem = _safe_name(group) if n == 1 else f"{_safe_name(group)}-{n}"
        final_path = self.videos_dir / f"{stem}.webm"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(raw_path), str(final_path))
        shutil.rmtree(raw_path.parent, ignore_errors=True)
        return str(final_path.relative_to(self.out_dir))

    def ensure_group(self, group: str, viewport: dict[str, int] | None) -> str | None:
        """Switch context if entering a new group or an explicit viewport
        override. Returns the finalized video path of the PREVIOUS group,
        if any."""
        vp = viewport or self.default_viewport
        need_new = group != self._current_group or (
            viewport is not None and self._current_viewport != viewport
        )
        if not need_new:
            return None
        finalized = self._close_context()
        self._open_context(viewport=vp, group=group)
        return finalized

    # -- auth ----------------------------------------------------------

    def ensure_pre_goto_auth(self) -> None:
        """Called by act_goto before navigating: form login runs first so
        the subsequent goto lands authenticated."""
        auth = self.cfg.auth
        if self._auth_applied or auth.method != "form" or not auth.auto_login:
            return
        self.perform_form_login()

    def ensure_post_goto_auth(self) -> None:
        """Called by act_goto after navigating: localStorage injection
        needs an origin page loaded before it can write, then a reload."""
        auth = self.cfg.auth
        if self._auth_applied or auth.method != "localstorage":
            return
        token = get_env(auth.token_env)
        if not token:
            return
        self.page.evaluate(
            "([k, t]) => window.localStorage.setItem(k, t)", [auth.ls_key, token]
        )
        for k, v in auth.ls_extra_items.items():
            self.page.evaluate("([k, v]) => window.localStorage.setItem(k, v)", [k, str(v)])
        self.page.reload(wait_until="domcontentloaded")
        self._auth_applied = True

    def perform_form_login(self) -> None:
        """Run the configured form-login flow in the current context."""
        auth = self.cfg.auth
        if auth.method != "form":
            raise ValueError("auth.method is not 'form' -- login_form action unavailable")
        username = get_env(auth.username_env)
        password = get_env(auth.password_env)
        if not (username and password):
            raise ValueError(
                f"Form login needs credentials in ${auth.username_env} / ${auth.password_env} "
                "(environment or .env). Use a disposable TEST account, never a real one."
            )
        from .actions import _url_for

        self.page.goto(_url_for(self, auth.login_path), wait_until="domcontentloaded")
        self.page.fill(auth.username_selector, username)
        self.page.fill(auth.password_selector, password)
        self.page.click(auth.submit_selector)
        if auth.success_selector:
            self.page.wait_for_selector(auth.success_selector, state="visible")
        self._auth_applied = True

    # -- media ---------------------------------------------------------

    def next_shot_name(self, step: Step, suffix: str = "") -> str:
        self._shot_counter += 1
        base = f"{self._shot_counter:03d}_{_safe_name(step.name)}"
        if suffix:
            base += f"_{_safe_name(suffix)}"
        return base + ".png"

    def screenshot(self, step: Step, suffix: str = "") -> str:
        name = self.next_shot_name(step, suffix)
        path = self.shots_dir / name
        self.page.screenshot(path=str(path))
        return str(path.relative_to(self.out_dir))

    def override_session_id(self, logical_name: str) -> str:
        """Force the page's session id (per config js_override) to a fresh
        prefixed id BEFORE a conversation's first message, so runs are
        identifiable/cleanable among concurrent real traffic."""
        si = self.cfg.session_isolation
        if not si.enabled:
            raise ValueError(
                "session_isolation is not enabled in ccwalk.yaml -- the override_session "
                "action requires it (and an app whose session id is client-overridable)."
            )
        new_id = f"{si.prefix}{logical_name}-{int(time.time() * 1000)}"
        self.page.evaluate(si.js_override, new_id)
        self.session_ids[logical_name] = new_id
        return new_id


# ---------------------------------------------------------------------------
# Tour execution
# ---------------------------------------------------------------------------


def evaluate_assertions(page, assertions: list[Assertion]) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for a in assertions:
        desc = a.description or a.selector
        try:
            if a.min_count is not None:
                # Poll up to timeout_ms like the other assertion shapes --
                # an instant count() right after an async action is a race.
                deadline = time.monotonic() + a.timeout_ms / 1000.0
                count = page.locator(a.selector).count()
                while count < a.min_count and time.monotonic() < deadline:
                    page.wait_for_timeout(150)
                    count = page.locator(a.selector).count()
                passed = count >= a.min_count
                results.append(
                    AssertionResult(desc, passed, f"found {count}, expected >= {a.min_count}")
                )
            elif a.text_contains is not None:
                page.wait_for_selector(a.selector, timeout=a.timeout_ms, state="attached")
                locator = page.locator(a.selector).first
                # input/textarea/select content lives in .value, not
                # .textContent (always '' for them) -- try input_value()
                # first, fall back to text_content() for everything else.
                try:
                    text = locator.input_value() or ""
                except Exception:
                    text = locator.text_content() or ""
                passed = a.text_contains.lower() in text.lower()
                results.append(
                    AssertionResult(
                        desc, passed, f"text_contains {a.text_contains!r} in {text[:120]!r}"
                    )
                )
            else:
                page.wait_for_selector(a.selector, timeout=a.timeout_ms, state="visible")
                results.append(AssertionResult(desc, True, "visible"))
        except Exception as e:  # noqa: BLE001 -- assertion failures are data, not crashes
            results.append(AssertionResult(desc, False, f"{type(e).__name__}: {e}"))
    return results


def _attach_video(results: list[StepResult], video_path: str) -> None:
    """Attach a just-finalized video segment to the most recent step that
    actually EXECUTED (skipping blocked steps, which never touched the
    page). The segment that just closed always belongs to the context the
    previous executed step ran in -- regardless of whether the context
    switch was a group change or a same-group viewport change."""
    for prior in reversed(results):
        if prior.status != "blocked":
            prior.video_path = video_path
            return


def run_walkthrough(
    steps: list[Step],
    cfg: Config,
    out_dir: Path,
    headed: bool = False,
    record_video: bool = True,
) -> list[StepResult]:
    results: list[StepResult] = []
    blocked_group: str | None = None
    blocked_by: str = ""
    with Runner(cfg, out_dir, headed=headed, record_video=record_video) as rt:
        for step in steps:
            # A failed step leaves its group's shared page in an unknown
            # state; running the group's remaining steps would just burn
            # timeouts against a broken page and report misleading
            # independent FAILs. Mark them blocked instead. The next group
            # opens a fresh context (goto-first invariant) and proceeds.
            if blocked_group is not None and step.group != blocked_group:
                blocked_group = None
            if blocked_group is not None:
                blocked = StepResult(step=step, status="blocked")
                blocked.error = (
                    f"not executed: step {blocked_by!r} failed earlier in "
                    f"group {step.group!r}"
                )
                results.append(blocked)
                continue

            t0 = time.monotonic()
            result = StepResult(step=step)
            prev_video = rt.ensure_group(step.group, step.viewport)
            if prev_video and results:
                _attach_video(results, prev_video)
            try:
                for action_dict in step.actions:
                    info = run_action(rt, step, action_dict)
                    if info.get("screenshot"):
                        result.screenshots.append(info["screenshot"])
                    if info.get("progress_screenshots"):
                        result.screenshots.extend(info["progress_screenshots"])
                    if info.get("timed_out"):
                        result.assertion_results.append(
                            AssertionResult(
                                f"{action_dict['action']} completed in time",
                                False,
                                info.get("timeout_detail", "timed out"),
                            )
                        )
                    if info:
                        result.log.append(f"{action_dict['action']}: {info}")
                if step.capture in ("screenshot", "both"):
                    result.screenshots.append(rt.screenshot(step, suffix="final"))
                result.assertion_results.extend(
                    evaluate_assertions(rt.page, step.assertions)
                )
                if any(not r.passed for r in result.assertion_results):
                    result.status = "warn"  # assertion failed; the tour continues
            except Exception as e:  # noqa: BLE001 -- keep the tour going
                result.status = "fail"
                result.error = f"{type(e).__name__}: {e}"
                result.log.append(traceback.format_exc())
                blocked_group = step.group
                blocked_by = step.name
                try:
                    result.screenshots.append(rt.screenshot(step, suffix="error"))
                except Exception:
                    pass
            result.duration_ms = (time.monotonic() - t0) * 1000
            results.append(result)
        # finalize the last context's video
        final_video = rt._close_context()  # noqa: SLF001
        if final_video and results:
            _attach_video(results, final_video)
    return results


def run_capture_only(
    target: str,
    viewports: list[tuple[int, int]],
    cfg: Config,
    out_dir: Path,
    headed: bool = False,
) -> list[StepResult]:
    """Design-capture mode: screenshot one page at each viewport, once per
    configured capture variant (config `capture_variants`, e.g. a dark-mode
    toggle). No video, no assertions."""
    variants: list[dict[str, Any]] = [{"label": "", "actions": []}]
    variants += [
        {"label": v.get("label", f"variant{i}"), "actions": v.get("actions", [])}
        for i, v in enumerate(cfg.capture_variants, start=1)
    ]
    results: list[StepResult] = []
    with Runner(cfg, out_dir, headed=headed, record_video=False) as rt:
        seq = 0
        for width, height in viewports:
            for variant in variants:
                label = variant["label"]
                name = f"{target.strip('/').replace('/', '_') or 'root'}_{width}x{height}"
                if label:
                    name += f"_{label}"
                step = Step(
                    name=name,
                    description=f"{target} @ {width}x{height}" + (f" ({label})" if label else ""),
                    group="design-capture",
                    actions=[{"action": "goto", "url": target}],
                )
                t0 = time.monotonic()
                result = StepResult(step=step)
                try:
                    # Fresh browser context per viewport x variant: a
                    # variant's actions may persist state (localStorage
                    # theme toggles, cookies), and a shared context would
                    # contaminate every later capture - the "default"
                    # variant must always show the app's true default.
                    seq += 1
                    rt.ensure_group(
                        f"design-capture-{seq}",
                        {"width": width, "height": height},
                    )
                    run_action(rt, step, {"action": "goto", "url": target})
                    for action_dict in variant["actions"]:
                        run_action(rt, step, action_dict)
                    rt.page.wait_for_timeout(500)
                    result.screenshots.append(rt.screenshot(step))
                except Exception as e:  # noqa: BLE001
                    result.status = "fail"
                    result.error = f"{type(e).__name__}: {e}"
                result.duration_ms = (time.monotonic() - t0) * 1000
                results.append(result)
    return results
