"""Spec validation/loading, config loading, and helper tests.

Ported from the predecessor system's suite (its
tests/test_visual_walkthrough.py) and extended for the ccwalk config layer and the two
new spec invariants (group contiguity, goto-first)."""

from __future__ import annotations

import pytest

from cc_visual_walkthrough import Assertion, Step, load_spec, validate_steps
from cc_visual_walkthrough.config import load_config
from cc_visual_walkthrough.helpers import parse_viewports, read_env_var


def _step(name="s1", actions=None, capture="screenshot", group="misc"):
    return Step(
        name=name,
        description="desc",
        actions=actions
        if actions is not None
        else [{"action": "goto", "url": "/"}, {"action": "wait_ms", "ms": 1}],
        group=group,
        capture=capture,
    )


class TestValidateSteps:
    def test_valid_spec_passes(self):
        validate_steps([_step("a"), _step("b")])  # no raise

    def test_empty_spec_rejected(self):
        with pytest.raises(ValueError, match="no steps"):
            validate_steps([])

    def test_missing_name_rejected(self):
        with pytest.raises(ValueError, match="no name"):
            validate_steps([_step("")])

    def test_duplicate_name_rejected(self):
        with pytest.raises(ValueError, match="Duplicate"):
            validate_steps([_step("dup"), _step("dup")])

    def test_empty_actions_rejected(self):
        with pytest.raises(ValueError, match="no actions"):
            validate_steps([_step("a", actions=[])])

    def test_bad_capture_value_rejected(self):
        with pytest.raises(ValueError, match="invalid capture"):
            validate_steps([_step("a", capture="gif")])

    def test_action_missing_action_key_rejected(self):
        with pytest.raises(ValueError, match="missing 'action' key"):
            validate_steps([_step("a", actions=[{"url": "/x"}])])

    def test_interleaved_groups_rejected(self):
        """The group-contiguity invariant: chat -> gate -> chat bit a real
        run of the predecessor (blank-page context on re-entry), so it is
        now a validation error, not a runtime surprise."""
        steps = [_step("a", group="chat"), _step("b", group="gate"), _step("c", group="chat")]
        with pytest.raises(ValueError, match="re-entered"):
            validate_steps(steps)

    def test_contiguous_groups_pass(self):
        steps = [
            _step("a", group="chat"),
            _step("b", group="chat"),
            _step("c", group="gate"),
        ]
        validate_steps(steps)  # no raise

    def test_group_first_step_must_goto(self):
        steps = [_step("a", actions=[{"action": "click", "selector": "#x"}])]
        with pytest.raises(ValueError, match="does not begin with a 'goto'"):
            validate_steps(steps)

    def test_login_form_counts_as_group_opener(self):
        steps = [_step("a", actions=[{"action": "login_form"}])]
        validate_steps(steps)  # no raise

    def test_pre_goto_actions_allowed_before_opener(self):
        steps = [
            _step(
                "a",
                actions=[
                    {"action": "mock_route", "url_pattern": "**/x", "json_body": {}},
                    {"action": "goto", "url": "/"},
                ],
            )
        ]
        validate_steps(steps)  # no raise

    def test_non_opening_step_in_group_needs_no_goto(self):
        steps = [
            _step("a", group="g"),
            _step("b", group="g", actions=[{"action": "click", "selector": "#x"}]),
        ]
        validate_steps(steps)  # no raise


class TestLoadSpec:
    def test_load_spec_from_file_path(self, tmp_path):
        spec_file = tmp_path / "tour.py"
        spec_file.write_text(
            "from cc_visual_walkthrough import Step\n"
            "STEPS = [Step(name='home', description='d', "
            "actions=[{'action': 'goto', 'url': '/'}])]\n"
        )
        steps = load_spec(str(spec_file))
        assert len(steps) == 1
        assert steps[0].name == "home"

    def test_load_spec_missing_steps_raises(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("X = 1\n")
        with pytest.raises(ValueError, match="no STEPS"):
            load_spec(str(bad))

    def test_load_spec_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            load_spec("nope/definitely_missing.py")

    def test_demo_tour_spec_is_valid(self):
        """The bundled demo spec must always import cleanly and pass
        validation -- catches typos without a browser."""
        steps = load_spec("demo/tour.py")
        assert len(steps) >= 5
        names = [s.name for s in steps]
        assert len(names) == len(set(names))
        groups = {s.group for s in steps}
        assert {"login", "notes", "analysis", "mobile"} <= groups


class TestParseViewports:
    def test_bare_widths_get_default_heights(self):
        assert parse_viewports("390,768,1440") == [(390, 844), (768, 1024), (1440, 900)]

    def test_explicit_wxh_pairs(self):
        assert parse_viewports("390x844,1024x768") == [(390, 844), (1024, 768)]

    def test_mixed_and_whitespace(self):
        assert parse_viewports(" 390 , 1024x768 ") == [(390, 844), (1024, 768)]

    def test_empty_segments_skipped(self):
        assert parse_viewports("390,,768") == [(390, 844), (768, 1024)]


class TestReadEnvVar:
    def test_finds_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n# BAZ=commented\nQUX=1\n")
        assert read_env_var("FOO", env_file) == "bar"
        assert read_env_var("BAZ", env_file) is None
        assert read_env_var("MISSING", env_file) is None

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('TOKEN="abc123"\n')
        assert read_env_var("TOKEN", env_file) == "abc123"

    def test_missing_file(self, tmp_path):
        assert read_env_var("FOO", tmp_path / "nope.env") is None


class TestLoadConfig:
    def test_missing_file_yields_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "ccwalk.yaml")
        assert cfg.app.base_url == "http://localhost:8000"
        assert cfg.auth.method == "none"
        assert cfg.capture.video is True
        assert cfg.report.embed is False

    def test_full_config_parses(self, tmp_path):
        cfg_file = tmp_path / "ccwalk.yaml"
        cfg_file.write_text(
            """
version: 1
app:
  name: "Acme"
  base_url: "http://localhost:9999/"
  start_command: "make run"
  ready_check: { path: "/healthz", timeout_s: 30 }
auth:
  method: form
  auto_login: false
  form:
    login_path: "/signin"
    username_selector: "#u"
    password_selector: "#p"
    submit_selector: "#go"
    success_selector: "#dash"
    username_env: U_ENV
    password_env: P_ENV
session_isolation:
  enabled: true
  prefix: "tour-"
capture:
  video: false
  default_viewport: { width: 1280, height: 720 }
  page_timeout_ms: 9000
report:
  out_dir: "out/reports"
  embed: true
  keep_runs: 3
specs_dir: "tours"
default_spec: "main"
custom_actions: "tours/actions.py"
"""
        )
        cfg = load_config(cfg_file)
        assert cfg.app.name == "Acme"
        assert cfg.app.base_url == "http://localhost:9999"  # trailing slash stripped
        assert cfg.app.ready_check.path == "/healthz"
        assert cfg.auth.method == "form"
        assert cfg.auth.auto_login is False
        assert cfg.auth.username_selector == "#u"
        assert cfg.auth.username_env == "U_ENV"
        assert cfg.session_isolation.enabled is True
        assert cfg.session_isolation.prefix == "tour-"
        assert cfg.capture.video is False
        assert cfg.capture.page_timeout_ms == 9000
        assert cfg.report.embed is True
        assert cfg.report.keep_runs == 3
        # Relative config paths resolve against the config file's dir
        assert cfg.specs_dir == str(cfg_file.parent / "tours")
        assert cfg.custom_actions == str(cfg_file.parent / "tours/actions.py")

    def test_invalid_auth_method_rejected(self, tmp_path):
        cfg_file = tmp_path / "ccwalk.yaml"
        cfg_file.write_text("auth:\n  method: magic\n")
        with pytest.raises(ValueError, match="auth.method"):
            load_config(cfg_file)

    def test_token_env_picked_up_from_any_method_block(self, tmp_path):
        cfg_file = tmp_path / "ccwalk.yaml"
        cfg_file.write_text(
            "auth:\n  method: header\n  header:\n    token_env: MY_TOKEN\n"
        )
        cfg = load_config(cfg_file)
        assert cfg.auth.token_env == "MY_TOKEN"


class TestAssertionDataclass:
    def test_defaults(self):
        a = Assertion(selector="#x")
        assert a.timeout_ms == 5000
        assert a.text_contains is None
        assert a.min_count is None


class TestDoctorAuthExemption:
    def _cfg(self, method="form", login_path="/login"):
        from cc_visual_walkthrough.config import load_config
        import textwrap, tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ccwalk.yaml")
            with open(p, "w") as fh:
                fh.write(textwrap.dedent(f"""\
                    version: 1
                    app: {{ base_url: "http://localhost:8500" }}
                    auth:
                      method: {method}
                      form:
                        login_path: "{login_path}"
                        username_selector: "#u"
                        password_selector: "#p"
                        submit_selector: "#s"
                        username_env: X_U
                        password_env: X_P
                    """))
            return load_config(p)

    def test_login_page_is_exempt(self):
        from cc_visual_walkthrough.doctor import auth_exempt
        cfg = self._cfg()
        assert auth_exempt(cfg, "/login")
        assert auth_exempt(cfg, "http://localhost:8500/login")
        assert auth_exempt(cfg, "/login/")

    def test_other_pages_are_not_exempt(self):
        from cc_visual_walkthrough.doctor import auth_exempt
        cfg = self._cfg()
        assert not auth_exempt(cfg, "/dashboard")
        assert not auth_exempt(cfg, "/")

    def test_no_form_auth_never_exempts(self):
        from cc_visual_walkthrough.doctor import auth_exempt
        cfg = self._cfg(method="none")
        assert not auth_exempt(cfg, "/login")

    def test_doctor_no_auth_flag_parses(self):
        from cc_visual_walkthrough.cli import build_arg_parser
        args = build_arg_parser().parse_args(["doctor", "/x", "--no-auth"])
        assert args.no_auth is True

    def test_report_embed_flags_parse(self):
        from cc_visual_walkthrough.cli import build_arg_parser
        args = build_arg_parser().parse_args(["report", "rd", "--embed", "--in-place"])
        assert args.embed and args.in_place
