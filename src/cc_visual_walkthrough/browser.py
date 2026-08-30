"""Browser launch with a system-chromium fallback.

Some boxes cannot run `playwright install-deps` (no root), but already
have a shared-libs-satisfied system chromium. Try the Playwright-managed
browser first, then each known system path."""

from __future__ import annotations

from pathlib import Path

_FALLBACK_CHROMIUM_PATHS = [
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def launch_browser(playwright, headless: bool = True):
    last_error: Exception | None = None
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as e:  # noqa: BLE001 -- any launch failure triggers fallback
        last_error = e
    for candidate in _FALLBACK_CHROMIUM_PATHS:
        if not Path(candidate).exists():
            continue
        try:
            return playwright.chromium.launch(headless=headless, executable_path=candidate)
        except Exception as e:  # noqa: BLE001
            last_error = e
    raise RuntimeError(
        "Could not launch any chromium (playwright-managed or system fallback). "
        f"Last error: {last_error}. Run `ccwalk install-browsers` to install "
        "Playwright's chromium (if that fails on missing shared libraries, "
        "install libnspr4/libnss3 system packages)."
    )
