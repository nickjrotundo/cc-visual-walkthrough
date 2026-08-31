# CC Visual Walkthrough

[![CI](https://github.com/nickjrotundo/cc-visual-walkthrough/actions/workflows/ci.yml/badge.svg)](https://github.com/nickjrotundo/cc-visual-walkthrough/actions/workflows/ci.yml)

Spec-driven visual walkthroughs for [Claude Code](https://claude.com/claude-code):
records and captures browser tours of your web app into shareable HTML
reports -- per-step screenshots, per-group video, and non-fatal regression
assertions -- with Claude Code generating and maintaining the tour spec for
you.

Every visual testing tool on the market exists to *gate merges*: red
builds, baseline approvals, pixel diffs. This one produces the artifact an
AI-driven development loop actually needs instead: **evidence that the app
works end-to-end after this iteration**, in a form both humans (HTML with
embedded media) and the agent itself (Markdown twin + `run_meta.json`) can
read. It is deliberately not a test framework -- if you need gating
regression tests, use Playwright's own runner alongside it.

## What a run produces

```
reports/walkthrough/<UTC timestamp>/
  report.html        # dark-theme report: screenshots, video, PASS/WARN/FAIL badges
  report.md          # same content as Markdown -- agent- and diff-friendly
  run_meta.json      # machine-readable per-step results (the triage interface)
  screenshots/*.png
  videos/<group>.webm
```

Assertions never abort the tour: a failed assertion marks the step WARN
and the run continues, because a transient timeout should not destroy an
evidence-gathering pass. An action that *throws* (selector never appeared)
marks the step FAIL, captures an error screenshot, and still continues.
The process exits non-zero only on FAIL.

## Install (Claude Code -- the supported path)

```
/plugin marketplace add nickjrotundo/cc-visual-walkthrough
/plugin install ccwalk@cc-visual-walkthrough
```

Then, in the project you want toured:

```
/ccwalk:setup
```

The setup skill inspects your project, finds the dev server and routes,
asks which flows matter, writes `ccwalk.yaml` and a tailored spec, runs a
verification pass, and teaches your project's `CLAUDE.md` to regenerate
the tour after each feature wave. After that:

```
/ccwalk:run
```

runs the tour and triages the results (real regression vs. flaky selector
vs. environment hiccup).

The plugin needs the `ccwalk` CLI on PATH (the setup skill checks and
offers to do this):

```bash
uv tool install cc-visual-walkthrough           # from PyPI
# or straight from the repo:
#   uv tool install git+https://github.com/nickjrotundo/cc-visual-walkthrough
# or from a local checkout, into a venv:
#   uv pip install /path/to/cc-visual-walkthrough
# one-time browser install (works for pip/uv tool/pipx installs alike):
ccwalk install-browsers
```

> The `ccwalk` CLI can be driven by hand without Claude Code, but that
> path is unsupported -- you are on your own.

## Supported platforms

Linux and WSL2 are tested. macOS should work (Playwright is
cross-platform) but is untested and has no system-chromium fallback --
use `ccwalk install-browsers`. Native Windows is unsupported:
`--start-app` process management is POSIX-only.

## Serving reports

The built-in server is the browsing story -- especially on WSL2, ssh,
or any headless box where "just open the HTML file" is not a thing:

```bash
ccwalk serve --daemon     # background server; prints the index URL
ccwalk serve status       # running? where?
ccwalk serve stop
```

It serves the report directory at `http://127.0.0.1:8378/` with a
generated **runs index** at `/`: one row per run, newest first, with its
PASS/WARN/FAIL counts, spec, git head, and duration -- click a run to
open its report. Every response is `Cache-Control: no-store`, so the
index is always current. `serve` (start) doubles as restart; localhost
only unless you explicitly `--bind 0.0.0.0`. WSL2: localhost forwarding
to the Windows browser usually works, but not always - if it doesn't,
open the URL in a Linux browser (e.g. WSLg-launched Chrome). The setup
skill offers to start this server after the first verified run, and
`/ccwalk:serve` manages it any time.

Alternatives still work: `report.html` opens fully from `file://` in
Chromium-family browsers (images and webm play). For Safari/iOS you need
both `--mp4` (webm does not play there) and a Range-capable server: the
stdlib server (including `ccwalk serve` and `python3 -m http.server`)
does NOT support Range requests and will not fix Safari video -- use
`npx serve`, caddy, or nginx. `--embed` produces a single self-contained
file you can attach to an email.

## The pieces

- **Spec** -- a Python module with a `STEPS: list[Step]`. Python, not
  YAML: real tours need real control flow. Each `Step` has a name, a
  `group` (steps in a group share one browser context and one video
  segment), a list of action dicts, and optional non-fatal assertions.
- **Actions** -- `goto`, `click`, `fill`, `press`, `hover`,
  `select_option`, `upload_file`, `wait_for`, `wait_ms`, `set_viewport`,
  `screenshot`, `scroll_into_view`, `login_form`, `override_session`,
  `mock_route`, and `wait_for_condition` (screenshots a progress state
  while polling -- how slow async work gets captured mid-flight).
  App-specific verbs go in a `custom_actions` module.
- **Auth** -- configured, not coded: `form` (auto-login per fresh
  context), `localstorage`, `cookie`, `header`, or `none`. Credentials
  are env-var *names* in config; values live in your environment or
  `.env`. Use a disposable test account.
- **Design capture mode** -- `ccwalk run --capture-only /page
  --viewports 390,768,1440` screenshots one page across viewports (and
  configured `capture_variants`, e.g. a dark-mode toggle) for design
  review.
- **Doctor** -- `ccwalk doctor /page --find "Submit"` prints stable
  selector candidates (data-testid > id > role > text) for fixing a
  failing step.
- **Single-file report** -- `ccwalk report <run_dir> --embed` re-renders
  a run into a self-contained `report_embedded.html` (all media inlined,
  email-attachable); `--mp4` transcodes videos for Safari (needs
  ffmpeg). `/ccwalk:help` gives a live status + command reference in a
  Claude Code session.

## Try the bundled demo

```bash
git clone https://github.com/nickjrotundo/cc-visual-walkthrough
cd cc-visual-walkthrough && uv sync && uv run ccwalk install-browsers
CCWALK_DEMO_USER=demo CCWALK_DEMO_PASS=demo123 \
  uv run ccwalk run --config demo/ccwalk.yaml --start-app
```

This boots a tiny FastAPI + htmx notes app, tours it (login flow, CRUD,
a deliberately slow "analyze" operation captured mid-progress, a mobile
viewport), and writes the report to `reports/walkthrough/`. A committed
example of the output lives in [`examples/`](https://github.com/nickjrotundo/cc-visual-walkthrough/tree/main/examples).

## Documentation

- [DESIGN.md](https://github.com/nickjrotundo/cc-visual-walkthrough/blob/main/DESIGN.md) -- positioning, architecture, and the design
  decisions (most of them learned the hard way in the system this was
  extracted from)
- [ANALYSIS.md](https://github.com/nickjrotundo/cc-visual-walkthrough/blob/main/ANALYSIS.md) -- honest limitations and the v0.2 roadmap
- [BUILD-LOG.md](https://github.com/nickjrotundo/cc-visual-walkthrough/blob/main/BUILD-LOG.md) -- how this repo was built with Claude
  Code, as a worked example of AI-driven development

## Support

Questions and bugs: [GitHub Issues](https://github.com/nickjrotundo/cc-visual-walkthrough/issues).

Example prompts once the plugin is installed:

1. `/ccwalk:setup` - inventory this app, generate a tour spec, and run it
2. "run the walkthrough and triage anything that fails" (`/ccwalk:run`)
3. `/ccwalk:serve` - start the reports server and give me the link
