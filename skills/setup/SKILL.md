---
name: setup
description: One-time interactive setup that tailors a visual walkthrough to this project - discovers the dev server and routes, asks which flows matter, writes ccwalk.yaml and a tour spec, verifies it with a real run, and teaches CLAUDE.md to regenerate the tour after each feature wave. Use when the user wants to set up, install, or configure a visual walkthrough for their web app, or re-run to update an existing tour.
---

# ccwalk setup

Tailor cc-visual-walkthrough to this project. Work through the phases in
order. If `ccwalk.yaml` already exists, jump to **Update mode** at the end.

## Phase 0 - eligibility and prerequisites

1. Confirm this project serves a web UI: look for frontend frameworks in
   package.json, template/static dirs with HTML, Django/Flask/FastAPI/Rails
   route files returning HTML, or a docker-compose service exposing a web
   port. If there is no web UI, say so and stop - this tool drives
   browsers; do not scaffold anything.
2. Confirm the `ccwalk` CLI is available (`ccwalk --version`). If not,
   install it - PRIMARY path first:
   `uv tool install "${CLAUDE_PLUGIN_ROOT}"` - the plugin root IS the
   full installable source tree, so this works regardless of whether the
   package has been published anywhere yet. Alternatives when the user
   wants a published build: `uv tool install cc-visual-walkthrough`
   (PyPI) or
   `uv tool install git+https://github.com/nickjrotundo/cc-visual-walkthrough`;
   or into a project venv: `uv pip install "${CLAUDE_PLUGIN_ROOT}"`.
   Then ensure a chromium is available: `ccwalk install-browsers` (this
   works regardless of how ccwalk was installed; a system chromium is
   used as fallback automatically on Linux).
3. Version check (stale-build guard): compare `ccwalk --version` with
   the plugin's own version
   (`grep '"version"' "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"`).
   If they differ, the CLI on PATH is an older build that may lack
   behavior this skill relies on - reinstall from the plugin's source
   before continuing (`uv tool install --force "${CLAUDE_PLUGIN_ROOT}"`,
   or `uv pip install --force-reinstall "${CLAUDE_PLUGIN_ROOT}"` into
   the venv in use), re-check, and tell the user what you did and why.

## Phase 1 - dev server

Determine, in order of confidence: an already-running local server (probe
common ports include 3000/4200/5000/5173/8000/8080/8500/8888 - but probe
any port the project's own config or README names FIRST); package.json scripts
(dev > start > serve); Procfile/docker-compose web service; framework
defaults (manage.py runserver:8000, flask run:5000, rails s:3000). Record
`app.base_url`, `app.start_command`, and a `ready_check` path (an existing
/health route if you find one, else "/"). If nothing is confident, ask the
user how they start the app and on what URL.

## Phase 2 - discover surface area

Build a page inventory two ways and merge:
- **Static**: enumerate routes per framework (Next.js app/pages dirs,
  React Router route elements, Django urls.py, Flask/FastAPI decorated
  HTML routes, rails routes). Flag parameterized routes as needing an
  example value.
- **Dynamic (MPA)**: with the app running, crawl same-origin links from
  the homepage (depth 2, cap ~40 pages) using `ccwalk doctor <path>` per
  page to snapshot candidate STABLE selectors (prefer data-testid, then
  id, then role+name, then unique text - never bare CSS classes). Note
  any redirect-to-login or 401/403 as an auth wall.
- **Dynamic (SPA)**: a single-page app has no links to crawl - its
  surface lives behind interactions (drawers, modals, panels). Use bare
  `ccwalk doctor <path>` (it inventories buttons/links/inputs/headings
  with suggested selectors) for the landed screen, and READ THE COMPONENT
  SOURCE for everything behind a click: doctor cannot see past
  interactions, so mid-flow selectors come from source or a throwaway
  Playwright probe script.

## Phase 3 - auth (only if auth walls exist)

Ask the user which method fits, offering what you detected:
- **form**: identify username/password/submit selectors from the login
  page DOM; credentials come from env vars the user names. Tell them
  plainly: use a disposable TEST account, never a real one. Verify `.env`
  is gitignored before pointing credentials at it; warn and fix if not.
- **localstorage / cookie / header**: grep the frontend for how it reads
  auth (localStorage.getItem, cookie name, Authorization header) and
  propose the exact key/name.
- **skip**: tour public pages only.
Config stores env-var NAMES only - never values.

## Phase 4 - propose the tour

Draft a grouped step list from the inventory (groups = user-facing flows:
onboarding, core CRUD, settings, mobile...). Then ONE AskUserQuestion
round: which flows to include (multiSelect, pre-select the core ones);
destructive-action policy (skip / run against test data / propose-then-
cancel at the confirmation step); viewports (desktop only / + mobile
group); video on or off. Free-text answers become extra steps - implement
unknown interactions as custom actions in a module referenced by
`custom_actions:`.

## Phase 5 - generate

Write:
- `ccwalk.yaml` (schema: see the cc_visual_walkthrough.config module
  docstring, or demo/ccwalk.yaml in the tool repo for a worked example)
- `walkthrough/specs/core_tour.py` - the Step list. Hard rules the
  validator enforces: steps of a group contiguous in STEPS; every group's
  first step begins with a goto (or login_form); every step gets at least
  one visibility assertion using the stable selectors from Phase 2.
- `walkthrough/specs/actions_local.py` only if custom actions are needed
  (module must expose `register(actions)`).
- `.env.example` with the env-var names -- only when auth is configured;
  with `auth: none` there are no env vars, so write no file.

## Phase 6 - verify (max 3 fix rounds)

1. Run: `ccwalk run` (add `--start-app` if you configured start_command
   and nothing is running).
2. Read `reports/walkthrough/<latest>/run_meta.json` - never eyeball the
   HTML first; the JSON is the triage interface. Its per-step data is the
   `results` array (name, group, status, screenshots, error, assertions,
   and for failed steps a `log` with the traceback).
3. For each warn/fail step: look at its screenshot FIRST (is the UI
   actually broken, or is the selector wrong?). Selector bug on a landed
   page: run `ccwalk doctor <url> --find "visible text"` and patch the
   spec; for a selector behind an interaction (drawer/modal), doctor
   cannot see it - read the component source instead. Real app bug:
   report it to the user as a genuine finding - do NOT weaken the
   assertion to make the tour pass. Steps marked `blocked` were skipped
   because an earlier step in their group failed - fix the failing step
   first; the blocked ones are not independent failures.
4. Report any residual warns honestly, classified: app bug vs timing vs
   selector.
5. Offer the report server: once the run is green (or triaged), ask via
   AskUserQuestion whether to start the local report server now
   (recommend yes - opening HTML files by hand is not a real viewing
   story on WSL2/remote boxes). On yes: `ccwalk serve --daemon`, then
   give the user the index URL it prints (the fresh report is the top
   row, one click in; on WSL2 localhost from the Windows browser usually
   works but not always - a Linux browser like WSLg Chrome does).
   Mention `ccwalk serve stop` and `/ccwalk:serve`.

## Phase 7 - install the recurring behavior

Append to the project's CLAUDE.md (create the section if absent):

```markdown
## Visual walkthrough
This project has a walkthrough spec at walkthrough/specs/core_tour.py
(config: ccwalk.yaml). After completing any feature wave, UI change, or
round of testing, regenerate the tour and review it:
    ccwalk run
Then read reports/walkthrough/<latest>/run_meta.json; investigate any
warn/fail steps (screenshot first, then `ccwalk doctor`). When you add a
user-facing feature, add a corresponding Step to the spec in the same
change. Keep group steps contiguous; a group's first step must goto.
```

Finish by telling the user: the report path of the verification run (and
its served URL if the report server is running), the step count and
status summary, and that `/ccwalk:run` regenerates the tour any time.

## Update mode (ccwalk.yaml exists)

Re-run Phase 2 discovery, diff the inventory against the current spec,
and propose only deltas ("3 new routes found, 1 spec route now 404s").
Specs are user-owned code: edit them like source, preserving user
customizations - never regenerate wholesale unless the user explicitly
asks for a rebuild.
