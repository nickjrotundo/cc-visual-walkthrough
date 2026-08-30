"""Spec data model: Step / Assertion and their result types, plus spec
loading and validation.

A WALKTHROUGH SPEC is a plain Python module exposing a module-level
``STEPS: list[Step]``. Python (not YAML/JSON) is deliberate: real tours
need real control flow -- polling the DOM during an in-flight async
operation, threading a session id across steps, mocking one network route
so a wizard renders -- and Python keeps that logic next to the step that
needs it instead of growing a mini expression language inside YAML.

Two invariants are enforced at validation time because both bit real runs
of the predecessor system (see DESIGN.md):

1. **Groups must be contiguous.** Steps sharing a ``group`` share one
   browser context (and one video segment). Leaving a group and re-entering
   it later would silently hand the re-entering step a blank page, so a
   spec that interleaves groups is rejected outright.
2. **Every group's first step must start with a ``goto``.** A fresh
   context starts on ``about:blank``; assuming a page from an earlier,
   non-adjacent block is still loaded is exactly the failure mode
   invariant 1 exists to prevent.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Actions that establish a page in a fresh context, accepted as a group's
# opening action. login_form navigates to the login page itself, so it is
# a valid opener for auth-walled groups.
_OPENING_ACTIONS = {"goto", "login_form"}

# Actions that are allowed to precede the opening goto without defeating
# its purpose (they configure the context/page, not the document).
_PRE_GOTO_ACTIONS = {"mock_route", "set_viewport", "wait_ms"}


@dataclass
class Assertion:
    """A single non-fatal expectation checked after a step's actions run.

    Exactly one of `selector` alone (visibility check), `text_contains`
    (selector's text must contain this substring, case-insensitive), or
    `min_count` (number of elements matching `selector` must be >= this)
    should be the active check -- text_contains and min_count both require
    `selector` too. Assertion failures NEVER abort the tour; they mark the
    step ``warn`` and the run continues, because a transient timeout or a
    slow backend should not destroy an evidence-gathering pass.
    """

    selector: str
    description: str = ""
    text_contains: str | None = None
    min_count: int | None = None
    timeout_ms: int = 5000


@dataclass
class Step:
    name: str
    description: str
    actions: list[dict[str, Any]]
    group: str = "misc"
    # Controls the automatic FINAL screenshot only: "screenshot"/"both"
    # take one after the actions run; "video"/"none" do not. Per-group
    # video recording is global (config `capture.video` / --no-video),
    # not per-step.
    capture: str = "screenshot"
    viewport: dict[str, int] | None = None
    assertions: list[Assertion] = field(default_factory=list)
    notes: str = ""


@dataclass
class AssertionResult:
    description: str
    passed: bool
    detail: str = ""


@dataclass
class StepResult:
    step: Step
    screenshots: list[str] = field(default_factory=list)
    video_path: str | None = None
    assertion_results: list[AssertionResult] = field(default_factory=list)
    duration_ms: float = 0.0
    # "pass" | "warn" (assertion failed / wait timed out) | "fail" (an
    # action raised) | "blocked" (not executed: an earlier step in the
    # same group failed, so this step would have run against a broken page)
    status: str = "pass"
    error: str | None = None
    log: list[str] = field(default_factory=list)


def validate_steps(steps: list[Step], known_actions: set[str] | None = None) -> None:
    """Raise ValueError if the spec is malformed. Called before a run so a
    typo in a spec file fails fast instead of mid-tour. Pass the action
    registry's names as ``known_actions`` (after loading custom actions)
    to also reject typo'd action verbs up front."""
    if not steps:
        raise ValueError("Spec contains no steps")
    seen_names: set[str] = set()
    for i, step in enumerate(steps):
        if not step.name:
            raise ValueError(f"Step {i} has no name")
        if step.name in seen_names:
            raise ValueError(f"Duplicate step name: {step.name!r}")
        seen_names.add(step.name)
        if not step.actions:
            raise ValueError(f"Step {step.name!r} has no actions")
        if step.capture not in ("screenshot", "video", "both", "none"):
            raise ValueError(f"Step {step.name!r}: invalid capture {step.capture!r}")
        for a in step.actions:
            if "action" not in a:
                raise ValueError(f"Step {step.name!r}: action dict missing 'action' key: {a}")
            if known_actions is not None and a["action"] not in known_actions:
                raise ValueError(
                    f"Step {step.name!r}: unknown action {a['action']!r} "
                    f"(known: {sorted(known_actions)})"
                )

    # Invariant 1: groups must be contiguous.
    seen_groups: set[str] = set()
    prev_group: str | None = None
    for step in steps:
        if step.group != prev_group:
            if step.group in seen_groups:
                raise ValueError(
                    f"Group {step.group!r} re-entered at step {step.name!r}: steps of a "
                    "group must be consecutive (a group exit + re-entry opens a fresh "
                    "blank-page context). Reorder the STEPS list."
                )
            seen_groups.add(step.group)
            # Invariant 2: a group's first step must establish a page.
            opener_ok = False
            for a in step.actions:
                if a["action"] in _OPENING_ACTIONS:
                    opener_ok = True
                    break
                if a["action"] not in _PRE_GOTO_ACTIONS:
                    break
            if not opener_ok:
                raise ValueError(
                    f"Step {step.name!r} opens group {step.group!r} but does not begin "
                    "with a 'goto' (or 'login_form'): a new group starts on a blank "
                    "page, so its first step must navigate somewhere."
                )
        prev_group = step.group


def load_spec(spec: str, known_actions: set[str] | None = None) -> list[Step]:
    """Load a spec from a dotted module path (``walkthroughs.core``) or a
    filesystem path (``specs/core_tour.py``) and return its validated
    STEPS list. Import errors inside the spec module surface as
    ValueError so the CLI can print them cleanly."""
    try:
        if spec.endswith(".py") or "/" in spec or "\\" in spec:
            path = Path(spec)
            if not path.exists():
                raise ValueError(f"Spec file not found: {spec}")
            module_spec = importlib.util.spec_from_file_location(path.stem, path)
            if module_spec is None or module_spec.loader is None:
                raise ValueError(f"Cannot import spec file: {spec}")
            mod = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(mod)
        else:
            mod = importlib.import_module(spec)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 -- surface spec bugs as clean CLI errors
        raise ValueError(f"Spec {spec!r} failed to import: {type(e).__name__}: {e}") from e
    steps = getattr(mod, "STEPS", None)
    if steps is None:
        raise ValueError(f"{spec} has no STEPS list")
    validate_steps(steps, known_actions=known_actions)
    return steps
