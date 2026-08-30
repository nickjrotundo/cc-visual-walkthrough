---
name: help
description: Show ccwalk's current status and a quick reference of common commands. Use when the user asks for ccwalk help, what ccwalk can do, its status, or its available commands.
---

# ccwalk help

Give a QUICK status + command reference. Gather real state first (do not
guess), then present it compactly - a short status block and a one-line-
per-command table. No long prose.

## 1. Gather status

- `ccwalk --version`; compare with the plugin version in
  `"${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"` - on mismatch,
  flag the stale build and offer
  `uv tool install --force "${CLAUDE_PLUGIN_ROOT}"`.
- Is this project set up? (`ccwalk.yaml` present?)
- Latest run, if any: newest dir under the configured report out_dir
  (default `reports/walkthrough/`); read its `run_meta.json` for the
  timestamp and PASS/WARN/FAIL counts.
- Report server: `ccwalk serve status` (running + URL, or not).

## 2. Present

A status block (version, set-up?, latest run summary, server state with
URL), then this table - one line each, current flags only:

| Command | What it does |
|---|---|
| `/ccwalk:setup` | Tailor a tour to this app (discovery, auth, spec, verified run) |
| `/ccwalk:run` | Run the tour and triage results |
| `ccwalk run` | Run the tour (`--start-app` boots the app, `--no-video` quick pass, `--capture-only <path>` design screenshots) |
| `ccwalk serve` | Serve the reports index in the background with `--daemon`; `serve stop` / `serve status` (or `/ccwalk:serve`) |
| `ccwalk report <run_dir>` | Re-render a report (`--embed` writes a self-contained report_embedded.html) |
| `ccwalk doctor <url>` | Selector help: bare = element inventory, `--find "text"` targets, `--no-auth` skips login |
| `ccwalk install-browsers` | Install Playwright chromium for this install |

End with: reports live under the configured out_dir; the served index
(when running) is the easiest way to browse them.
