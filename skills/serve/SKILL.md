---
name: serve
description: Start, restart, or stop the local walkthrough report server and hand the user the browsing link. Use when the user wants to view reports in a browser, serve the reports, get a report link, or stop the report server.
---

# ccwalk serve

Manage the local report server. It serves the project's report directory
with a generated runs index at `/` - one row per run, newest first, with
PASS/WARN/FAIL counts, each linking to that run's report.html.

Preamble (stale-build guard): compare `ccwalk --version` with the
plugin's version (`grep '"version"' "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"`).
On mismatch, the CLI on PATH is an older build - reinstall from the
plugin source first (`uv tool install --force "${CLAUDE_PLUGIN_ROOT}"`,
or `uv pip install --force-reinstall "${CLAUDE_PLUGIN_ROOT}"` into the
venv in use) and tell the user you did.

- **Default (no argument, or "start"/"restart")**: run
  `ccwalk serve --daemon`. Start doubles as restart - any previous
  server is stopped and replaced. Then give the user the exact index URL
  from the output (e.g. `http://127.0.0.1:8378/`) and say the newest run
  is the top row. On WSL2, localhost forwarding to the Windows browser
  usually works but not always - if not, suggest a Linux browser (e.g.
  WSLg-launched Chrome). Mention `ccwalk serve stop` (or
  `/ccwalk:serve stop`) for later.
- **"stop"**: run `ccwalk serve stop` and confirm the result.
- **"status"**: run `ccwalk serve status` and relay it (URL when
  running).

Notes worth passing on when relevant: every response is
`Cache-Control: no-store`, so the index and reports are always current;
the stdlib server has no Range support, so Safari will not play the
`.webm` videos from it - Chromium-family browsers play them fine, and
the Safari story is `ccwalk run --mp4` plus a range-capable server
(`npx serve`, caddy). The server binds localhost only unless the user
explicitly chooses `--bind 0.0.0.0`.
