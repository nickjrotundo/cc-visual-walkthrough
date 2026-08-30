"""cc-visual-walkthrough: spec-driven Playwright walkthroughs for Claude Code.

Records and captures browser tours of a live web app into shareable HTML +
Markdown reports (screenshots, per-group video, non-fatal regression
assertions). The supported workflow is through the Claude Code plugin
(slug: ccwalk); the `ccwalk` CLI can be driven by hand, but that path is
unsupported -- you are on your own.
"""

from .specs import Assertion, AssertionResult, Step, StepResult, load_spec, validate_steps

__version__ = "0.2.0"

__all__ = [
    "Assertion",
    "AssertionResult",
    "Step",
    "StepResult",
    "load_spec",
    "validate_steps",
    "__version__",
]
