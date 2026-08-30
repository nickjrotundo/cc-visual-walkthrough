"""Walkthrough spec for the bundled demo app (demo/app.py).

This doubles as the reference example of a real spec: a login flow shown
on-screen, an htmx CRUD flow, a slow async operation captured
mid-progress via wait_for_condition, and a mobile-viewport group.

Run it:  ccwalk run --config demo/ccwalk.yaml --start-app
(needs CCWALK_DEMO_USER=demo and CCWALK_DEMO_PASS=demo123 in the
environment or .env -- throwaway demo credentials, hardcoded in the demo
app on purpose.)
"""

from cc_visual_walkthrough import Assertion, Step
from cc_visual_walkthrough.config import MOBILE_VIEWPORT

STEPS = [
    # -- login: show the flow explicitly (apply_auth off so the tour
    # itself walks through the form; later groups auto-login via config).
    Step(
        name="login_page",
        description="The sign-in page as an anonymous visitor sees it",
        group="login",
        actions=[
            {"action": "goto", "url": "/login", "apply_auth": False},
            {"action": "wait_for", "selector": "[data-testid=login-form]"},
        ],
        assertions=[
            Assertion(selector="[data-testid=login-title]", description="login title visible"),
            Assertion(selector="[data-testid=login-submit]", description="submit button visible"),
        ],
    ),
    Step(
        name="login_submit",
        description="Filling credentials and signing in lands on the notes list",
        group="login",
        actions=[
            {"action": "fill", "selector": "[data-testid=login-user]", "value": "demo"},
            {"action": "fill", "selector": "[data-testid=login-pass]", "value": "demo123"},
            {"action": "click", "selector": "[data-testid=login-submit]"},
            {"action": "wait_for", "selector": "[data-testid=app-title]"},
        ],
        assertions=[
            Assertion(selector="[data-testid=app-title]", description="notes page reached"),
            Assertion(
                selector="[data-testid=empty-state]",
                description="empty state shown before any notes exist",
            ),
        ],
    ),
    # -- notes CRUD (fresh context; config form-auth logs in automatically)
    Step(
        name="add_notes",
        description="Adding two notes over htmx updates the list without a page reload",
        group="notes",
        actions=[
            {"action": "goto", "url": "/"},
            {"action": "fill", "selector": "[data-testid=note-input]", "value": "Ship the Q3 report"},
            {"action": "click", "selector": "[data-testid=note-add]"},
            {"action": "wait_for", "selector": "[data-testid=note-1]"},
            {"action": "fill", "selector": "[data-testid=note-input]", "value": "Buy espresso beans"},
            {"action": "click", "selector": "[data-testid=note-add]"},
            {"action": "wait_for", "selector": "[data-testid=note-2]"},
        ],
        assertions=[
            Assertion(selector=".card.note", min_count=2, description="two notes listed"),
            Assertion(
                selector="[data-testid=note-1] [data-testid=note-text]",
                text_contains="Q3 report",
                description="first note text correct",
            ),
        ],
    ),
    Step(
        name="delete_note",
        description="Deleting the second note removes it from the list",
        group="notes",
        actions=[
            {"action": "click", "selector": "[data-testid=delete-2]"},
            {"action": "wait_ms", "ms": 400},
        ],
        assertions=[
            Assertion(
                selector="[data-testid=note-1]", description="first note still present"
            ),
        ],
        notes="note-2 absence is implied by the final screenshot; presence-of-absence "
        "assertions are deliberately out of scope for v0.1.",
    ),
    # -- slow async analysis with progress capture
    Step(
        name="analyze_note",
        description="The Analyze action runs ~4s server-side; the tour captures the "
        "in-progress state and the final result",
        group="analysis",
        actions=[
            {"action": "goto", "url": "/"},
            {"action": "click", "selector": "[data-testid=analyze-1]"},
            {
                "action": "wait_for_condition",
                "js": "document.querySelector('[data-testid=analysis-result]') !== null",
                "timeout_ms": 15000,
                "capture_progress": True,
                "poll_interval_ms": 900,
                "progress_selector": "[data-testid=analysis-progress]",
            },
        ],
        assertions=[
            Assertion(
                selector="[data-testid=analysis-result]",
                text_contains="words",
                description="analysis result rendered",
            ),
        ],
    ),
    # -- responsive check
    Step(
        name="mobile_notes",
        description="The notes list on a phone-sized viewport",
        group="mobile",
        viewport=MOBILE_VIEWPORT,
        actions=[
            {"action": "goto", "url": "/"},
            {"action": "wait_for", "selector": "[data-testid=app-title]"},
        ],
        assertions=[
            Assertion(selector="[data-testid=note-form]", description="note form usable on mobile"),
        ],
    ),
]
