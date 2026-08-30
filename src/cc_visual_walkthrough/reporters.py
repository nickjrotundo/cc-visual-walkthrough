"""Report generation (HTML + Markdown + run_meta.json).

Pure functions over (run_meta, results) with no Playwright dependency, so
they are unit-testable with fake StepResult objects. All dynamic text is
HTML-escaped. Media is LINKED by default (small report.html next to
screenshots/ and videos/ -- the whole run directory is the artifact);
``embed=True`` inlines every screenshot and video as a base64 data URI,
producing one genuinely self-contained HTML file for the "attach it to an
email" case, at the cost of a much larger file.
"""

from __future__ import annotations

import base64
import dataclasses
import html
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .specs import AssertionResult, Step, StepResult

_MIME = {".png": "image/png", ".webm": "video/webm", ".mp4": "video/mp4", ".jpg": "image/jpeg"}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


# Files above this size stay linked even under --embed: a multi-hundred-MB
# data URI helps nobody and can hang the browser parsing it.
_EMBED_PER_FILE_CAP = 25 * 1024 * 1024


def _media_src(rel_path: str, out_dir: Path | None, embed: bool) -> str:
    if not embed or out_dir is None:
        return rel_path
    file_path = out_dir / rel_path
    try:
        if file_path.stat().st_size > _EMBED_PER_FILE_CAP:
            return rel_path
        data = file_path.read_bytes()
    except OSError:
        return rel_path
    mime = _MIME.get(file_path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _status_badge_html(status: str) -> str:
    colors = {"pass": "#2ecc71", "warn": "#f39c12", "fail": "#e74c3c", "blocked": "#8b9bb4"}
    color = colors.get(status, "#888")
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
        f'background:{color};color:#0b0e14;font-weight:600;font-size:0.8em;">'
        f"{_esc(status.upper())}</span>"
    )


def _report_title(run_meta: dict[str, Any]) -> str:
    app_name = run_meta.get("app_name") or ""
    return f"{app_name} Visual Walkthrough".strip()


def render_report_html(
    run_meta: dict[str, Any],
    results: list[StepResult],
    out_dir: Path | None = None,
    embed: bool = False,
) -> str:
    total = len(results)
    n_pass = sum(1 for r in results if r.status == "pass")
    n_warn = sum(1 for r in results if r.status == "warn")
    n_fail = sum(1 for r in results if r.status == "fail")
    n_blocked = sum(1 for r in results if r.status == "blocked")
    title = _report_title(run_meta)

    rows = []
    for i, r in enumerate(results, start=1):
        shots_html = "".join(
            f'<a href="{_esc(_media_src(s, out_dir, embed))}" target="_blank">'
            f'<img src="{_esc(_media_src(s, out_dir, embed))}" loading="lazy" '
            f'style="max-width:420px;border:1px solid #333;border-radius:6px;margin:4px;"></a>'
            for s in r.screenshots
        )
        video_html = ""
        if r.video_path:
            v_src = _esc(_media_src(r.video_path, out_dir, embed))
            v_mime = _MIME.get(Path(r.video_path).suffix.lower(), "video/webm")
            # Poster: without one, an unplayed <video> renders as a blank
            # rectangle and a green report looks half-broken in review.
            poster_attr = ""
            if r.screenshots:
                poster_attr = f' poster="{_esc(_media_src(r.screenshots[-1], out_dir, embed))}"'
            video_html = (
                f'<video controls preload="metadata"{poster_attr} '
                f'style="max-width:480px;margin-top:8px;'
                f'border-radius:6px;border:1px solid #333;"><source src="{v_src}" '
                f'type="{v_mime}"></video>'
            )
        assertions_html = "".join(
            f'<li style="color:{"#2ecc71" if a.passed else "#e74c3c"};">'
            f'{"PASS" if a.passed else "FAIL"} — {_esc(a.description)} '
            f'<span style="opacity:0.6;">({_esc(a.detail)})</span></li>'
            for a in r.assertion_results
        )
        error_html = (
            f'<pre style="color:#e74c3c;white-space:pre-wrap;font-size:0.8em;">{_esc(r.error)}</pre>'
            if r.error
            else ""
        )
        # Notes are where "this green step hides a known caveat/bug" lives
        # -- render them as a visible callout, not a whisper.
        notes_html = (
            f'<div style="border-left:3px solid #f39c12;background:#151a24;'
            f'padding:8px 12px;margin:8px 0;border-radius:0 6px 6px 0;">'
            f'<strong style="color:#f39c12;">Note</strong> '
            f'{_esc(r.step.notes)}</div>'
            if r.step.notes
            else ""
        )
        rows.append(
            f"""
        <section class="step" id="step-{i}">
          <h2>{i}. {_esc(r.step.name)} {_status_badge_html(r.status)}
            <span style="font-weight:400;font-size:0.7em;opacity:0.6;">
              group: {_esc(r.step.group)} · {r.duration_ms:.0f}ms
            </span>
          </h2>
          <p>{_esc(r.step.description)}</p>
          {notes_html}
          {error_html}
          {f'<ul style="margin:6px 0;">{assertions_html}</ul>' if assertions_html else ''}
          <div class="shots">{shots_html}</div>
          {video_html}
        </section>"""
        )

    health = run_meta.get("app_health", {})
    health_str = (
        "reachable" if health.get("reachable") else f"unreachable ({health.get('error')})"
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{_esc(title)} — {_esc(run_meta.get('timestamp', ''))}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#0b0e14; color:#e6e6e6; font-family: -apple-system, Segoe UI, sans-serif;
          max-width: 1100px; margin: 0 auto; padding: 24px; line-height:1.5; }}
  h1 {{ margin-bottom: 4px; }}
  header.meta {{ background:#151a24; border:1px solid #262b38; border-radius:10px;
                 padding:16px 20px; margin-bottom: 24px; font-size:0.9em; }}
  header.meta div {{ margin: 2px 0; }}
  .summary-badges span {{ margin-right: 10px; }}
  section.step {{ border-top: 1px solid #262b38; padding: 20px 0; }}
  section.step h2 {{ font-size:1.15em; }}
  .shots {{ display:flex; flex-wrap:wrap; gap:6px; }}
  img {{ background:#000; }}
  a {{ color: #7aa2f7; }}
  code {{ background:#151a24; padding:1px 5px; border-radius:4px; }}
</style>
</head>
<body>
<h1>{_esc(title)}</h1>
<header class="meta">
  <div><strong>Generated:</strong> {_esc(run_meta.get('timestamp', ''))}</div>
  <div><strong>Git HEAD:</strong> <code>{_esc(run_meta.get('git_head', ''))}</code></div>
  <div><strong>App:</strong> {_esc(run_meta.get('base_url', ''))} ({_esc(health_str)})</div>
  <div><strong>Spec:</strong> {_esc(run_meta.get('spec', ''))}</div>
  <div><strong>Tool:</strong> cc-visual-walkthrough {_esc(run_meta.get('tool_version', ''))}</div>
  <div class="summary-badges" style="margin-top:8px;">
    {total} steps —
    {_status_badge_html('pass')} {n_pass}
    {_status_badge_html('warn')} {n_warn}
    {_status_badge_html('fail')} {n_fail}
    {(_status_badge_html('blocked') + f' {n_blocked}') if n_blocked else ''}
  </div>
</header>
{''.join(rows)}
</body></html>
"""


def _md_text(text: str) -> str:
    """Minimal Markdown neutralization for step-authored text: keep it
    readable, stop brackets/backticks from mangling links and code spans."""
    return text.replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def render_report_md(run_meta: dict[str, Any], results: list[StepResult]) -> str:
    total = len(results)
    n_pass = sum(1 for r in results if r.status == "pass")
    n_warn = sum(1 for r in results if r.status == "warn")
    n_fail = sum(1 for r in results if r.status == "fail")
    n_blocked = sum(1 for r in results if r.status == "blocked")
    health = run_meta.get("app_health", {})
    health_str = (
        "reachable" if health.get("reachable") else f"unreachable ({health.get('error')})"
    )
    title = _report_title(run_meta)

    summary = f"- **{total} steps** — PASS {n_pass} / WARN {n_warn} / FAIL {n_fail}"
    if n_blocked:
        summary += f" / BLOCKED {n_blocked}"
    lines = [
        f"# {title}",
        "",
        f"- Generated: {run_meta.get('timestamp', '')}",
        f"- Git HEAD: `{run_meta.get('git_head', '')}`",
        f"- App: {run_meta.get('base_url', '')} ({health_str})",
        f"- Spec: {run_meta.get('spec', '')}",
        summary,
        "",
    ]
    for i, r in enumerate(results, start=1):
        lines.append(f"## {i}. {_md_text(r.step.name)} — {r.status.upper()}")
        lines.append(f"_group: {_md_text(r.step.group)} · {r.duration_ms:.0f}ms_")
        lines.append("")
        lines.append(_md_text(r.step.description))
        if r.step.notes:
            lines.append(f"\n> **Note:** {_md_text(r.step.notes)}")
        if r.error:
            lines.append(f"\n**Error:** `{r.error}`")
        if r.assertion_results:
            lines.append("")
            for a in r.assertion_results:
                mark = "x" if a.passed else " "
                lines.append(f"- [{mark}] {_md_text(a.description)} ({_md_text(a.detail)})")
        for s in r.screenshots:
            lines.append(f"\n![{_md_text(r.step.name)}]({s})")
        if r.video_path:
            lines.append(f"\n[video: {r.video_path}]({r.video_path})")
        lines.append("")
    return "\n".join(lines)


def write_report(
    run_meta: dict[str, Any],
    results: list[StepResult],
    out_dir: Path,
    embed: bool = False,
    in_place: bool = False,
) -> Path:
    # The linked report.html is always written; with embed=True the
    # self-contained variant lands in report_embedded.html alongside it
    # (or replaces report.html when in_place=True).
    linked = render_report_html(run_meta, results, out_dir=out_dir, embed=False)
    md = render_report_md(run_meta, results)
    primary = out_dir / "report.html"
    primary.write_text(linked)
    if embed:
        embedded = render_report_html(run_meta, results, out_dir=out_dir, embed=True)
        if in_place:
            primary.write_text(embedded)
        else:
            primary = out_dir / "report_embedded.html"
            primary.write_text(embedded)
    (out_dir / "report.md").write_text(md)
    (out_dir / "run_meta.json").write_text(
        json.dumps(
            {
                **run_meta,
                "results": [
                    {
                        "name": r.step.name,
                        "group": r.step.group,
                        "description": r.step.description,
                        "notes": r.step.notes,
                        "capture": r.step.capture,
                        "viewport": r.step.viewport,
                        "status": r.status,
                        "duration_ms": r.duration_ms,
                        "screenshots": r.screenshots,
                        "video_path": r.video_path,
                        "error": r.error,
                        "assertions": [dataclasses.asdict(a) for a in r.assertion_results],
                        # The captured traceback/action log -- previously
                        # collected but never emitted; failed steps need it
                        # for triage.
                        **({"log": r.log} if r.status == "fail" and r.log else {}),
                    }
                    for r in results
                ],
            },
            indent=2,
        )
    )
    return primary


def results_from_run_meta(run_meta: dict[str, Any]) -> list[StepResult]:
    """Reconstruct StepResults from a run_meta.json dict (the `ccwalk
    report` re-render path). The extended per-step fields written by
    write_report make this lossless for report purposes."""
    results: list[StepResult] = []
    for r in run_meta.get("results", []):
        step = Step(
            name=r.get("name", ""),
            description=r.get("description", ""),
            actions=[{"action": "noop"}],
            group=r.get("group", "misc"),
            capture=r.get("capture", "screenshot"),
            viewport=r.get("viewport"),
            notes=r.get("notes", ""),
        )
        results.append(
            StepResult(
                step=step,
                screenshots=list(r.get("screenshots", [])),
                video_path=r.get("video_path"),
                assertion_results=[
                    AssertionResult(
                        a.get("description", ""), bool(a.get("passed")), a.get("detail", "")
                    )
                    for a in r.get("assertions", [])
                ],
                duration_ms=float(r.get("duration_ms", 0)),
                status=r.get("status", "pass"),
                error=r.get("error"),
                # Preserve captured tracebacks through re-render round-trips:
                # write_report rewrites run_meta.json, so dropping `log` here
                # would permanently destroy a failed step's evidence.
                log=list(r.get("log", [])),
            )
        )
    return results


def transcode_videos_mp4(out_dir: Path, results: list[StepResult]) -> list[str]:
    """Transcode each .webm group video to H.264 .mp4 (Safari/iOS
    playback) and repoint results at the .mp4. Requires ffmpeg on PATH;
    returns warnings instead of failing when it is missing."""
    warnings: list[str] = []
    if not shutil.which("ffmpeg"):
        return ["ffmpeg not found on PATH -- skipping --mp4 transcode; videos stay .webm"]
    done: dict[str, str] = {}
    for r in results:
        if not r.video_path or not r.video_path.endswith(".webm"):
            continue
        if r.video_path in done:
            r.video_path = done[r.video_path]
            continue
        src = out_dir / r.video_path
        dst = src.with_suffix(".mp4")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-an", str(dst)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not dst.exists():
            warnings.append(f"ffmpeg failed for {r.video_path}: {proc.stderr[-300:]}")
            continue
        rel = str(dst.relative_to(out_dir))
        done[r.video_path] = rel
        r.video_path = rel
    return warnings
