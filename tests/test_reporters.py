"""Report renderer tests: structure, escaping, embed mode, run_meta
round-trip, and the mp4 transcode guard. Pure functions -- no browser."""

from __future__ import annotations

import base64
import json

from cc_visual_walkthrough.reporters import (
    render_report_html,
    render_report_md,
    results_from_run_meta,
    transcode_videos_mp4,
    write_report,
)
from cc_visual_walkthrough.specs import AssertionResult, Step, StepResult

META = {
    "timestamp": "20260101-000000",
    "git_head": "abc123",
    "base_url": "http://x",
    "app_health": {"reachable": True},
    "app_name": "Acme",
    "spec": "spec.mod",
    "tool_version": "0.1.0",
}


def _make_result(
    name="step1", status="pass", screenshots=None, video=None, assertions=None, error=None,
    description=None, notes="",
):
    return StepResult(
        step=Step(
            name=name,
            description=description or f"{name} description",
            actions=[{"action": "goto", "url": "/"}],
            group="g",
            notes=notes,
        ),
        screenshots=screenshots or [],
        video_path=video,
        assertion_results=assertions or [],
        duration_ms=123.4,
        status=status,
        error=error,
    )


class TestRenderReportHtml:
    def test_includes_summary_counts_and_title(self):
        results = [
            _make_result(status="pass"),
            _make_result("s2", status="warn"),
            _make_result("s3", status="fail", error="boom"),
        ]
        html = render_report_html(META, results)
        assert "3 steps" in html
        assert "abc123" in html
        assert "boom" in html
        assert "Acme Visual Walkthrough" in html
        assert "step1" in html and "s2" in html and "s3" in html

    def test_links_screenshots_and_video(self):
        r = _make_result(screenshots=["screenshots/001_step1_final.png"], video="videos/g.webm")
        html = render_report_html(META, [r])
        assert "001_step1_final.png" in html
        assert "videos/g.webm" in html
        assert "<video" in html
        assert "video/webm" in html

    def test_renders_assertion_pass_fail(self):
        ok = AssertionResult("looks right", True, "visible")
        bad = AssertionResult("looks wrong", False, "not found")
        html = render_report_html(META, [_make_result(assertions=[ok, bad])])
        assert "looks right" in html and "looks wrong" in html
        assert "PASS" in html and "FAIL" in html

    def test_unreachable_health_shown(self):
        meta = {**META, "app_health": {"reachable": False, "error": "refused"}}
        html = render_report_html(meta, [_make_result()])
        assert "unreachable" in html
        assert "refused" in html

    def test_dynamic_text_is_escaped(self):
        """The predecessor's renderer interpolated raw text; a step name or
        error containing markup must not become live HTML."""
        r = _make_result(
            name="x<script>alert(1)</script>",
            description='desc with <img src=x onerror=alert(1)>',
            error="Error: <b>bold</b>",
            notes="<i>note</i>",
            assertions=[AssertionResult('<script>a</script>', False, "<detail>")],
        )
        html = render_report_html(META, [r])
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "<img src=x" not in html
        assert "<b>bold</b>" not in html
        assert "<i>note</i>" not in html
        assert "<detail>" not in html

    def test_embed_inlines_media_as_data_uris(self, tmp_path):
        shots = tmp_path / "screenshots"
        shots.mkdir()
        png_bytes = b"\x89PNG\r\n\x1a\nfakepng"
        (shots / "a.png").write_bytes(png_bytes)
        r = _make_result(screenshots=["screenshots/a.png"])
        html = render_report_html(META, [r], out_dir=tmp_path, embed=True)
        expected = base64.b64encode(png_bytes).decode()
        assert f"data:image/png;base64,{expected}" in html
        assert 'src="screenshots/a.png"' not in html

    def test_embed_missing_file_falls_back_to_link(self, tmp_path):
        r = _make_result(screenshots=["screenshots/missing.png"])
        html = render_report_html(META, [r], out_dir=tmp_path, embed=True)
        assert "screenshots/missing.png" in html


class TestRenderReportMd:
    def test_basic_structure(self):
        results = [_make_result(status="pass"), _make_result("s2", status="fail", error="err!")]
        md = render_report_md(META, results)
        assert md.startswith("# Acme Visual Walkthrough")
        assert "PASS 1" in md and "FAIL 1" in md
        assert "spec.mod" in md
        assert "err!" in md

    def test_assertions_render_as_checkboxes(self):
        ok = AssertionResult("thing visible", True, "visible")
        bad = AssertionResult("thing missing", False, "timeout")
        md = render_report_md(META, [_make_result(assertions=[ok, bad])])
        assert "- [x] thing visible" in md
        assert "- [ ] thing missing" in md

    def test_screenshot_and_video_links(self):
        r = _make_result(screenshots=["screenshots/a.png"], video="videos/g.webm")
        md = render_report_md(META, [r])
        assert "![step1](screenshots/a.png)" in md
        assert "[video: videos/g.webm](videos/g.webm)" in md

    def test_untitled_app_gets_generic_title(self):
        meta = {**META, "app_name": ""}
        md = render_report_md(meta, [_make_result()])
        assert md.startswith("# Visual Walkthrough")


class TestWriteReport:
    def test_writes_all_three_files_with_extended_meta(self, tmp_path):
        r = _make_result(notes="a note")
        path = write_report(META, [r], tmp_path)
        assert path == tmp_path / "report.html"
        assert (tmp_path / "report.md").exists()
        meta_out = json.loads((tmp_path / "run_meta.json").read_text())
        assert meta_out["git_head"] == "abc123"
        entry = meta_out["results"][0]
        assert entry["name"] == "step1"
        assert entry["status"] == "pass"
        # Extended fields the predecessor dropped -- the triage loop needs them.
        assert entry["group"] == "g"
        assert entry["description"] == "step1 description"
        assert entry["notes"] == "a note"
        assert entry["capture"] == "screenshot"

    def test_round_trip_via_results_from_run_meta(self, tmp_path):
        original = [
            _make_result(
                screenshots=["screenshots/a.png"],
                video="videos/g.webm",
                assertions=[AssertionResult("ok", True, "visible")],
                status="warn",
            )
        ]
        write_report(META, original, tmp_path)
        meta = json.loads((tmp_path / "run_meta.json").read_text())
        rebuilt = results_from_run_meta(meta)
        assert len(rebuilt) == 1
        r = rebuilt[0]
        assert r.step.name == "step1"
        assert r.step.group == "g"
        assert r.screenshots == ["screenshots/a.png"]
        assert r.video_path == "videos/g.webm"
        assert r.status == "warn"
        assert r.assertion_results[0].description == "ok"
        # Re-render from the rebuilt results must not raise.
        html = render_report_html(meta, rebuilt)
        assert "step1" in html


class TestTranscodeMp4:
    def test_missing_ffmpeg_warns_instead_of_failing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cc_visual_walkthrough.reporters.shutil.which", lambda _: None)
        r = _make_result(video="videos/g.webm")
        warnings = transcode_videos_mp4(tmp_path, [r])
        assert len(warnings) == 1
        assert "ffmpeg not found" in warnings[0]
        assert r.video_path == "videos/g.webm"  # untouched


class TestWriteReportEmbedSibling:
    def _shot(self, tmp_path):
        shots = tmp_path / "screenshots"
        shots.mkdir(exist_ok=True)
        (shots / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
        return _make_result(screenshots=["screenshots/a.png"])

    def test_embed_writes_sibling_and_keeps_linked_primary(self, tmp_path):
        r = self._shot(tmp_path)
        path = write_report(META, [r], tmp_path, embed=True)
        assert path.name == "report_embedded.html"
        assert "data:image/png;base64," in path.read_text()
        linked = (tmp_path / "report.html").read_text()
        assert 'src="screenshots/a.png"' in linked
        assert "data:image/png;base64," not in linked

    def test_embed_in_place_overwrites_primary(self, tmp_path):
        r = self._shot(tmp_path)
        path = write_report(META, [r], tmp_path, embed=True, in_place=True)
        assert path.name == "report.html"
        assert "data:image/png;base64," in path.read_text()
        assert not (tmp_path / "report_embedded.html").exists()
