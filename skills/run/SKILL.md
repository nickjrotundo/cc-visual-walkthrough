---
name: run
description: Run the project's visual walkthrough and triage the results - report the PASS/WARN/FAIL summary, distinguish real regressions from flaky selectors or environment hiccups, and point at the report. Use when the user asks to run, regenerate, or check the visual walkthrough or UI tour, or after completing a feature wave.
---

# ccwalk run

1. **Preflight**: read `ccwalk.yaml` for base_url + ready_check. Confirm
   the app is reachable (curl the ready_check path). If it is not
   running: start it via the configured start_command (or run
   `ccwalk run --start-app` below) - if you cannot, say so and stop
   rather than launching a browser against nothing.
2. **Run**: `ccwalk run` (add `--start-app` if you are starting the app,
   `--no-video` for a quick pass, `--capture-only <path>` for a
   design-review screenshot pass).
3. **Triage** from `reports/walkthrough/<latest>/run_meta.json`:
   - FAIL steps: an action raised. Read the step's error + `_error`
     screenshot. Judge: real regression vs environment hiccup (server
     down, GPU/CPU contention, transient timeout). A selector that no
     longer exists after a UI change is a spec maintenance task: fix the
     spec with `ccwalk doctor <url> --find "text"`, and say you did.
   - WARN steps: an assertion failed but the tour continued. Look at the
     screenshot before concluding - the UI may be fine and the selector
     stale, or the UI may actually be broken. Never weaken an assertion
     just to go green; report genuine breakage to the user.
4. **Report back**, always: the report path (report.html and report.md),
   the per-step PASS/WARN/FAIL summary, total screenshots + videos
   captured, and for anything not PASS your judgment of real-regression
   vs. hiccup with one line of evidence. Check `ccwalk serve status`: if
   the report server is running, give its index URL too (the new run is
   the top row) - a clickable link beats a file path; if it is not
   running, mention that `/ccwalk:serve` starts it.
