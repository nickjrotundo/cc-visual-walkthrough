# Design

## Positioning: evidence, not gating

Every visual tool in the ecosystem gates merges. Playwright's own runner
and trace viewer are engineer debugging artifacts with pass/fail
semantics; Percy, Chromatic, and Argos answer "did pixels move against a
baseline" behind SaaS approval workflows; the AI wave (QA Wolf, Momentic,
Meticulous) sells AI-maintained *gating tests*. None of them produces the
artifact an AI-driven development loop actually needs: shareable proof
that the app works end-to-end after this iteration, in a form the agent
itself can read back and act on.

cc-visual-walkthrough is that evidence layer. Assertions collect rather
than fail; each run emits an HTML report for humans plus a Markdown twin
and `run_meta.json` for the agent. It is deliberately not a test
framework: teams needing gating regression tests should run Playwright's
runner alongside it. (Python Playwright does not even ship an HTML
reporter, so within the Python ecosystem there is no direct overlap at
all. Adjacent tools cover fragments: playwright-recast is video-only,
shot-scraper screenshots-only.)

The intended loop: Claude Code writes and maintains the tour spec
(/ccwalk:setup), the developer or agent regenerates the tour after every
feature wave (/ccwalk:run), and the report doubles as demo, onboarding
material, and regression evidence.

## Provenance

Extracted from a larger private project, where the predecessor
system ran at the end of every feature wave as part of a checkpoint
protocol and replaced ad-hoc Playwright sessions that left one-off
screenshots with nothing reusable. Several design decisions below cite
live failures from that system; the postmortems shipped with it.

## Decisions

**Specs are Python, not YAML.** Real tours need real control flow --
polling the DOM during an in-flight async operation, threading a session
id across steps, mocking one route so a wizard renders. Python keeps that
logic next to the step that needs it instead of inventing a mini
expression language inside YAML.

**Assertions are non-fatal by design.** A failed assertion = step WARN,
tour continues; only a raised action = step FAIL (and even then the tour
continues, capturing an error screenshot). Rationale: the report is
evidence; a transient timeout at step 3 must not destroy the evidence for
steps 4-19. The exit code (non-zero on FAIL) still gives CI a signal.

**Groups own contexts, and the validator enforces what the runtime
assumes.** Steps sharing a `group` share one browser context and one
video segment; a new group opens a fresh (blank) context. The predecessor
documented "keep groups contiguous" as folklore after a live run
silently broke (a chat -> gate -> chat spec handed the second chat block
a blank page; every selector timed out). Here that folklore is a
validation error, as is a group whose first step fails to `goto`.

**Auth is config, not code.** Five strategies (none / form / localstorage
/ cookie / header) declared in ccwalk.yaml; cookie and header apply at
context creation, form auto-login and localStorage injection apply on a
fresh context's first goto -- because auth state does NOT survive the
context switch at each group boundary, which is easy to forget and
painful to debug. Credentials are env-var names in config; values stay in
the environment or .env. The setup skill insists on a disposable test
account.

**The condition, not the spinner, ends a wait.** `wait_for_condition`
polls a JS expression as the authoritative completion signal; a progress
selector only paces screenshots. The predecessor tried three DOM-signal
designs and two failed live: gating on a spinner's visible->hidden
transition spun the full timeout on fast replies (the spinner was never
observed visible); breaking on a result element appearing fired too early
(the element rendered on the first streamed token). The internal poll is
also finer (300ms) than the screenshot cadence so near-instant
completions return promptly.

**Form-field text lives in .value.** The assertion evaluator tries
`input_value()` before `text_content()` because an `<input>`'s
textContent is always empty -- a live-run lesson that is now a regression
test.

**Reports link media by default; --embed makes single files.** The
predecessor's docs claimed self-contained HTML while the renderer linked
relative paths -- callers emailing report.html shipped broken pages. Here
the default is honest (the run directory is the artifact; report.html
stays ~30KB) and `--embed` actually inlines base64 media when one file is
worth its size. Everything dynamic is HTML-escaped (the predecessor
escaped nothing).

**App-specific verbs live outside the core.** The predecessor's registry
carried 12 app-specific actions (chat sends, sidebar toggles, admin
tabs). The core here ships only generic verbs; ccwalk.yaml points at a
`custom_actions` module exposing `register(actions)` for the app-shaped
ones. The demo ships one as a worked example.

**System-chromium fallback.** Boxes without root cannot run `playwright
install-deps`; if the managed browser cannot launch, known system
chromium paths are tried in order. Inherited unchanged -- it is what let
the predecessor run on a sandboxed dev box.

## Naming

Package/repo `cc-visual-walkthrough`, CLI and plugin slug `ccwalk`
(plugin slugs namespace every skill -- `/ccwalk:run` -- so the typed name
stays short while the searched name stays descriptive). Claude Code is
the only supported usage path; the CLI runs standalone but you are on
your own there.
