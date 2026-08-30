# Changelog

All notable changes to cc-visual-walkthrough. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.2.0] - 2026-08-30

Publish-readiness pass from an independent code review: the daemon
pid-ownership check works without `/proc` (falls back to `ps`; when
neither is available a live pid's pidfile is never auto-cleaned, so a
daemon can't be orphaned on macOS); an occupied port produces a clean
message naming `serve status`/`serve stop` instead of a traceback;
`ccwalk report` re-renders no longer destroy a failed step's captured
traceback (the `log` field survives the round-trip); `--capture-only`
uses a fresh browser context per viewport x variant so a variant's
persisted side effects (theme toggles, cookies) can't contaminate later
captures; Markdown report alt text is escaped; sdist excludes the local
serve log and dev docs; README links render on PyPI; the setup skill
installs the CLI from the plugin root first (works before and after
PyPI publication); version 0.2.0 everywhere with a test pinning
pyproject/`__init__`/plugin.json agreement.

## [0.1.0] - 2026-08-29

Live manual-testing round (pre-release): `ccwalk serve` -- a local
report server with a generated runs index at `/` (one row per run,
newest first, PASS/WARN/FAIL counts, linked reports; `--daemon` /
`serve stop` / `serve status`, pidfile-tracked, restart-on-start,
`Cache-Control: no-store` everywhere). The setup skill now offers to
start the server after the first verified run, the run skill hands back
the served index URL when the server is up, and two new skills landed:
`/ccwalk:serve` (start/restart/stop + link) and `/ccwalk:help` (live
status + command reference). Skills also gained a stale-build guard:
`ccwalk --version` is compared against the plugin's own version, with a
reinstall-from-plugin-source remedy on mismatch.

E2E dry-run polish (pre-release): local-checkout install path documented,
`ccwalk install-browsers` reports success plainly, `doctor` auto-exempts
the configured login page from auth (plus `--no-auth`), `ccwalk report
--embed` writes `report_embedded.html` alongside `report.html` (use
`--in-place` to overwrite), and the setup skill's port probe covers
8500/8888 and defers to the project's own config first.

Initial release, extracted and generalized from a larger private
project's internal visual-testing system, then hardened by a five-agent
adversarial review round (code review, real-project field test, release
audit) before publish.

### Added
- Spec-driven Playwright walkthrough runner: Python `Step` specs,
  per-group browser contexts and video segments, per-step screenshots,
  non-fatal assertions (WARN, never abort), FAIL-with-error-screenshot,
  blocked-step cascade when a group's step fails.
- Auth strategies via `ccwalk.yaml`: form auto-login, localStorage,
  cookie, header (header injection scoped to the app's origin only).
- Reports: dark-theme HTML (escaped, video posters, notes callouts),
  Markdown twin, extended `run_meta.json` (the agent triage interface,
  including tracebacks for failed steps); `--embed` single-file mode;
  `--mp4` Safari transcode.
- `ccwalk` CLI: `init`, `run` (`--start-app` with imposter refusal and
  process-group teardown, `--capture-only` design mode), `doctor`
  (selector finder with interactive-element inventory and quote-safe
  text selectors), `report` (re-render), `install-browsers`.
- Claude Code plugin (`ccwalk`): `/ccwalk:setup` tailoring skill and
  `/ccwalk:run` run-and-triage skill.
- Bundled FastAPI + htmx demo app with a committed example report; CI
  runs the real tour on every push and publishes it to GitHub Pages.
- 99 unit tests (no browser required) plus the demo tour as the
  browser-driving integration test.
