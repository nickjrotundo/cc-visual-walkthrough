"""ccwalk.yaml loading. Every app-specific behavior of the runner lives
behind this config -- the package core contains nothing about any one app.

Schema (all keys optional; defaults shown):

    version: 1
    app:
      name: "My App"                # report title prefix
      base_url: "http://localhost:8000"
      start_command: "npm run dev"  # used only with `ccwalk run --start-app`
      ready_check: { path: "/", timeout_s: 60 }
    auth:
      method: none                  # none | form | localstorage | cookie | header
      auto_login: true              # form only: log in automatically per fresh context
      form:
        login_path: "/login"
        username_selector: "#email"
        password_selector: "#password"
        submit_selector: "button[type=submit]"
        success_selector: "#dashboard"
        username_env: CCWALK_USER   # env var NAMES -- values live in env/.env
        password_env: CCWALK_PASS
      localstorage:
        key: api_token
        token_env: CCWALK_TOKEN
        extra_items: {}             # additional literal key/value pairs to set
      cookie:
        name: session
        token_env: CCWALK_TOKEN
      header:
        name: Authorization
        format: "Bearer {token}"
        token_env: CCWALK_TOKEN
    session_isolation:
      enabled: false
      js_override: "(sid) => { window.sessionId = sid; }"
      prefix: "ccwalk-"
    capture:
      video: true
      default_viewport: { width: 1440, height: 900 }
      page_timeout_ms: 20000
    report:
      out_dir: "reports/walkthrough"
      embed: false                  # true = base64 media into one HTML file
      keep_runs: 10                 # prune older run dirs (0 = keep all)
    specs_dir: "walkthrough/specs"
    default_spec: "core_tour"
    custom_actions: null            # path to a module exposing register(actions)
    capture_variants: []            # capture-only mode extras:
    #  - label: dark-mode
    #    actions: [{action: click, selector: "#theme-toggle"}]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "ccwalk.yaml"

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}


@dataclass
class ReadyCheck:
    path: str = "/"
    timeout_s: int = 60


@dataclass
class AppConfig:
    name: str = ""
    base_url: str = "http://localhost:8000"
    start_command: str = ""
    ready_check: ReadyCheck = field(default_factory=ReadyCheck)


@dataclass
class AuthConfig:
    method: str = "none"  # none | form | localstorage | cookie | header
    auto_login: bool = True
    # form
    login_path: str = "/login"
    username_selector: str = ""
    password_selector: str = ""
    submit_selector: str = ""
    success_selector: str = ""
    username_env: str = ""
    password_env: str = ""
    # localstorage
    ls_key: str = ""
    ls_extra_items: dict[str, str] = field(default_factory=dict)
    # cookie
    cookie_name: str = ""
    # header
    header_name: str = "Authorization"
    header_format: str = "Bearer {token}"
    # shared secret env-var name (localstorage/cookie/header)
    token_env: str = ""


@dataclass
class SessionIsolationConfig:
    enabled: bool = False
    js_override: str = "(sid) => { window.sessionId = sid; }"
    prefix: str = "ccwalk-"


@dataclass
class CaptureConfig:
    video: bool = True
    default_viewport: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    page_timeout_ms: int = 20000


@dataclass
class ReportConfig:
    out_dir: str = "reports/walkthrough"
    embed: bool = False
    keep_runs: int = 10


@dataclass
class Config:
    app: AppConfig = field(default_factory=AppConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    session_isolation: SessionIsolationConfig = field(default_factory=SessionIsolationConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    specs_dir: str = "walkthrough/specs"
    default_spec: str = "core_tour"
    custom_actions: str | None = None
    capture_variants: list[dict[str, Any]] = field(default_factory=list)
    source_path: Path | None = None  # where the config was loaded from


def _auth_from_dict(d: dict[str, Any]) -> AuthConfig:
    a = AuthConfig()
    a.method = d.get("method", "none")
    a.auto_login = bool(d.get("auto_login", True))
    form = d.get("form") or {}
    a.login_path = form.get("login_path", a.login_path)
    a.username_selector = form.get("username_selector", "")
    a.password_selector = form.get("password_selector", "")
    a.submit_selector = form.get("submit_selector", "")
    a.success_selector = form.get("success_selector", "")
    a.username_env = form.get("username_env", "")
    a.password_env = form.get("password_env", "")
    ls = d.get("localstorage") or {}
    a.ls_key = ls.get("key", "")
    a.ls_extra_items = dict(ls.get("extra_items") or {})
    cookie = d.get("cookie") or {}
    a.cookie_name = cookie.get("name", "")
    header = d.get("header") or {}
    a.header_name = header.get("name", a.header_name)
    a.header_format = header.get("format", a.header_format)
    a.token_env = (
        ls.get("token_env") or cookie.get("token_env") or header.get("token_env") or ""
    )
    valid = ("none", "form", "localstorage", "cookie", "header")
    if a.method not in valid:
        raise ValueError(f"auth.method must be one of {valid}, got {a.method!r}")
    return a


def load_config(path: str | Path | None = None) -> Config:
    """Load ccwalk.yaml from `path`, or from the current directory. A
    missing file yields pure defaults (the CLI can still run with flags)."""
    cfg = Config()
    cfg_path = Path(path) if path else Path.cwd() / CONFIG_FILENAME
    if not cfg_path.exists():
        return cfg
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path}: top level must be a mapping")

    app = raw.get("app") or {}
    cfg.app.name = app.get("name", "")
    cfg.app.base_url = str(app.get("base_url", cfg.app.base_url)).rstrip("/")
    cfg.app.start_command = app.get("start_command", "")
    rc = app.get("ready_check") or {}
    cfg.app.ready_check = ReadyCheck(
        path=rc.get("path", "/"), timeout_s=int(rc.get("timeout_s", 60))
    )

    cfg.auth = _auth_from_dict(raw.get("auth") or {})

    si = raw.get("session_isolation") or {}
    cfg.session_isolation = SessionIsolationConfig(
        enabled=bool(si.get("enabled", False)),
        js_override=si.get("js_override", cfg.session_isolation.js_override),
        prefix=si.get("prefix", cfg.session_isolation.prefix),
    )

    cap = raw.get("capture") or {}
    vp = cap.get("default_viewport") or {}
    cfg.capture = CaptureConfig(
        video=bool(cap.get("video", True)),
        default_viewport={
            "width": int(vp.get("width", DEFAULT_VIEWPORT["width"])),
            "height": int(vp.get("height", DEFAULT_VIEWPORT["height"])),
        },
        page_timeout_ms=int(cap.get("page_timeout_ms", 20000)),
    )

    rep = raw.get("report") or {}
    cfg.report = ReportConfig(
        out_dir=rep.get("out_dir", cfg.report.out_dir),
        embed=bool(rep.get("embed", False)),
        keep_runs=int(rep.get("keep_runs", 10)),
    )

    cfg.specs_dir = raw.get("specs_dir", cfg.specs_dir)
    cfg.default_spec = raw.get("default_spec", cfg.default_spec)
    cfg.custom_actions = raw.get("custom_actions")
    cfg.capture_variants = list(raw.get("capture_variants") or [])
    cfg.source_path = cfg_path

    # Relative paths in the config resolve against the CONFIG FILE's
    # directory, not the process CWD -- `ccwalk run --config demo/ccwalk.yaml`
    # must work from anywhere.
    base = cfg_path.parent
    def _rel(p: str) -> str:
        return p if not p or Path(p).is_absolute() else str(base / p)

    cfg.specs_dir = _rel(cfg.specs_dir)
    cfg.report.out_dir = _rel(cfg.report.out_dir)
    if cfg.custom_actions:
        cfg.custom_actions = _rel(str(cfg.custom_actions))
    return cfg
