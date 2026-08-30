# Build log: how this repo was built with Claude Code

This repo was produced by an AI-driven build, documented here as a worked
example of the workflow the tool itself supports. Times are 2026-08-29.

## Lineage

The core was not invented for a portfolio. It was extracted from a
larger private project, where the predecessor script
(scripts/visual_walkthrough.py, 1131 lines) ran at the end of every
feature wave as step 5 of a checkpoint protocol, and its unit suite
(~50 tests) plus an architecture doc (PLAN/VISUAL-TESTING.md) shipped
alongside it. Three of its bugs were found on live runs and are cited in
DESIGN.md; their fixes carried over here as regression tests.

## Process

1. **Research fan-out (multi-agent).** Before any code: one agent
   inventoried the predecessor source line by line (producing the
   generic-vs-app-specific split that became the extraction plan); one
   researched Claude Code plugin distribution mechanics; one researched
   the competitive landscape (Playwright reporter, Percy/Chromatic/
   Argos, QA Wolf/Momentic, playwright-recast, shot-scraper) and ranked
   improvement ideas; one drafted the setup-skill flow. The synthesis
   lives in the parent repo's PLAN-standalone-tools.md.
2. **Decision round.** Three decision agents with different lenses
   (client credibility, engineering pragmatism, OSS adoption)
   independently answered the open design questions, cross-pollinated
   positions, and converged unanimously on: clean-root repo, linked
   media + --embed, MIT, FastAPI+HTMX demo, Python 3.11 floor,
   <name>.yaml config. Naming went to the human (it is taste), who chose
   cc-visual-walkthrough / ccwalk over the agents' pick.
3. **Build.** A single orchestrator agent wrote the package as focused
   modules (specs/config/browser/actions/runner/reporters/doctor/cli),
   porting the predecessor's proven mechanics (group-context lifecycle,
   video finalization, non-fatal assertions, chromium fallback) while
   fixing its recorded defects: no HTML escaping, the false
   "self-contained report" claim, inert capture semantics, hardcoded
   auth, and 12 app-specific actions in the core registry.
4. **Tests.** The predecessor's suite was ported and extended to 80
   tests, all browser-free (mocked Playwright), including new coverage
   for the config layer, auth strategies, embed mode, and the two spec
   invariants that had only been folklore before (group contiguity,
   goto-first).
5. **Verification.** The bundled demo app (FastAPI + vendored htmx) was
   toured for real: 6/6 PASS, the slow "analyze" operation captured
   mid-progress in 5 wait-state screenshots. That run is committed
   unedited as examples/demo-report. Two real bugs were found and fixed
   during this pass: a missing python-multipart dependency (uvicorn died
   at boot) and an over-broad attribute selector in the demo spec.

## The adversarial review round (post-build, pre-publish)

Five agents reviewed the finished v0.1 in parallel: an adversarial code
review, a field test driving the tool against a real unrelated project
(a Vite/React/Leaflet SPA), a release-readiness audit, and two
equivalents for the sibling status-watchdog project. What they caught --
with 80 unit tests already green -- reshaped the release:

- The code review found (and verified by repro) that a mid-group
  viewport override corrupted video attribution and silently overwrote
  footage; that a timed-out `wait_for_condition` reported PASS -- the
  worst failure mode an evidence tool can have; that `doctor` crashed on
  pages containing quote characters; that `--start-app` teardown could
  leak the app past exit and bless an imposter server on the port; and
  that header auth leaked the bearer token to every cross-origin
  request. All fixed, each with a regression test.
- The field test got from install to a green 8/8 report on a real SPA
  without human rescue -- and in doing so surfaced a genuine crash bug
  in the TARGET app (a Leaflet follow-mode infinite-tiles crash with no
  error boundary), which the skill's rules handled honestly: documented
  in the step's notes, routed around via the app's own UI, never
  papered over by weakening an assertion. Exactly the tool's purpose,
  demonstrated on its first field outing. The test also showed the
  mechanical-discovery story (link crawl + bare doctor) contributes
  little on class-based SPAs -- which produced the doctor inventory
  mode, the SPA guidance in the setup skill, and the blocked-step
  cascade.
- The release audit produced the platform matrix, the install-story
  fixes (`ccwalk install-browsers`, the git-install fallback), the
  serving documentation (including the fact that `python3 -m
  http.server` cannot fix Safari video -- no Range support), and the
  packaging polish.

The meta-lesson, recorded here deliberately: the unit suite was green
while three advertised entry paths were broken. The missing tests were
integration-shaped, and the review round -- agents adversarially
attacking a sibling agent's finished work -- is what found them.

## What the human decided vs. what the agents decided

Human: the project's existence, both names, CC-first positioning
(standalone use unsupported), the deployment targets, and every
escalated taste call. Agents: everything else, through the research ->
decision-consensus -> build -> verify pipeline above, with each
inherited design decision either justified in DESIGN.md or replaced
with a recorded reason.
