"""`ccwalk doctor` -- the selector finder used by the fix-a-failing-step
loop. Loads a page (honoring the configured auth, like `run` does) and
prints candidate STABLE selectors, ranked data-testid > id > role+name >
text.

Modes:
- ``--find TEXT``: leaf-most elements whose text contains TEXT.
- bare (no --find): a full inventory of interactive/landmark elements
  (buttons, links, inputs, selects, headings, [role], [data-testid],
  [id]) -- class-based SPAs often have no testids or ids at all, and an
  inventory of role+name candidates is what a spec author actually needs.

Known limit (documented in ANALYSIS.md): doctor inspects the LANDED page
only. Elements behind interactions (drawers, modals, post-click states)
are invisible to it -- read the component source or write a throwaway
Playwright probe for those.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .config import Config

_COLLECT_JS = """
([query, allMode]) => {
  const q = (query || "").toLowerCase();
  const out = [];
  const push = (el) => {
    let ancestorTestid = null;
    let node = el;
    while (node && node !== document.body) {
      if (node.hasAttribute && node.hasAttribute("data-testid")) {
        ancestorTestid = node.getAttribute("data-testid");
        break;
      }
      node = node.parentElement;
    }
    const aria = el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("placeholder"));
    out.push({
      tag: el.tagName.toLowerCase(),
      testid: el.getAttribute("data-testid"),
      ancestorTestid: ancestorTestid,
      id: el.id || null,
      role: el.getAttribute("role"),
      name: el.getAttribute("name"),
      aria: aria || null,
      type: el.getAttribute("type"),
      text: (el.textContent || "").trim().slice(0, 60),
    });
  };
  if (q) {
    const all = Array.from(document.querySelectorAll("*"));
    for (const el of all) {
      if (["SCRIPT", "STYLE", "META", "LINK", "HEAD"].includes(el.tagName)) continue;
      const text = (el.textContent || "").trim();
      if (!text.toLowerCase().includes(q)) continue;
      // leaf-most: skip if a child also contains the query
      const childHas = Array.from(el.children).some(
        (c) => (c.textContent || "").toLowerCase().includes(q)
      );
      if (childHas) continue;
      push(el);
      if (out.length >= 25) break;
    }
  } else {
    const sel = allMode
      ? "button, a[href], input, select, textarea, h1, h2, h3, [role], [data-testid], [id]"
      : "[data-testid], [id]";
    const els = Array.from(document.querySelectorAll(sel));
    for (const el of els) {
      if (["SCRIPT", "STYLE", "META", "LINK", "HEAD", "HTML", "BODY"].includes(el.tagName)) continue;
      push(el);
      if (out.length >= 60) break;
    }
  }
  return out;
}
"""


def _escape_text_for_selector(text: str) -> str:
    """Make arbitrary page text safe inside :has-text("..."): escape
    backslashes and double quotes, and drop a trailing backslash the
    truncation may have exposed."""
    t = text[:30].rstrip("\\")
    return t.replace("\\", "\\\\").replace('"', '\\"')


def _suggest(entry: dict) -> str:
    if entry.get("testid"):
        return f'[data-testid="{entry["testid"]}"]'
    if entry.get("id"):
        return f'#{entry["id"]}'
    if entry.get("ancestorTestid"):
        return f'[data-testid="{entry["ancestorTestid"]}"] {entry["tag"]}'
    if entry.get("text"):
        return f'{entry["tag"]}:has-text("{_escape_text_for_selector(entry["text"])}")'
    if entry.get("aria"):
        return f'{entry["tag"]}[aria-label="{_escape_text_for_selector(entry["aria"])}"]'
    if entry.get("role"):
        return f'{entry["tag"]}[role="{entry["role"]}"]'
    if entry.get("name"):
        return f'{entry["tag"]}[name="{entry["name"]}"]'
    return entry["tag"]


def _safe_count(page, selector: str):
    """A malformed selector must never crash doctor -- report '?' instead."""
    try:
        return page.locator(selector).count()
    except Exception:  # noqa: BLE001
        return "?"


def auth_exempt(cfg, url: str) -> bool:
    """True when doctoring `url` must not demand credentials: the
    configured form-login page itself never needs the auth it collects."""
    target_path = url.split("?", 1)[0].rstrip("/")
    login_path = (cfg.auth.login_path or "").rstrip("/")
    return bool(
        cfg.auth.method == "form" and login_path and target_path.endswith(login_path)
    )


def run_doctor(
    cfg: Config,
    url: str,
    find: str | None,
    headed: bool = False,
    no_auth: bool = False,
) -> int:
    """Load `url` (resolved against cfg base_url, applying configured
    auth) and print selector candidates. Returns 0 if any were found.

    The configured login page itself is auto-exempt from auth: doctoring
    /login must never demand the credentials it exists to collect."""
    import dataclasses

    from .runner import Runner

    if no_auth or auth_exempt(cfg, url):
        cfg = dataclasses.replace(cfg, auth=dataclasses.replace(cfg.auth, method="none"))

    with tempfile.TemporaryDirectory(prefix="ccwalk-doctor-") as tmp:
        with Runner(cfg, Path(tmp), headed=headed, record_video=False) as rt:
            rt.ensure_group("doctor", None)
            from .actions import act_goto
            from .specs import Step

            probe = Step(name="doctor", description="", actions=[], group="doctor")
            act_goto(rt, probe, url)
            rt.page.wait_for_timeout(500)
            entries = rt.page.evaluate(_COLLECT_JS, [find or "", True])
            target = rt.page.url
            counts: dict[str, object] = {}
            for e in entries:
                sel = _suggest(e)
                if sel not in counts:
                    counts[sel] = _safe_count(rt.page, sel)

    if not entries:
        what = f"matching {find!r}" if find else "of interest (no interactive elements?)"
        print(f"No elements {what} found on {target}")
        return 1
    header = f"Selector candidates on {target}" + (f" for text {find!r}:" if find else ":")
    print(header)
    seen: set[str] = set()
    for e in entries:
        sel = _suggest(e)
        if sel in seen:
            continue
        seen.add(sel)
        n = counts.get(sel, "?")
        uniq = "UNIQUE" if n == 1 else f"matches {n}"
        print(f"  {sel:<50s} [{uniq}]  <{e['tag']}> {e['text'][:50]!r}")
    print(
        "\nPrefer [data-testid=...] > #id > text > role selectors; a UNIQUE match is "
        "safe to assert on. Doctor sees the landed page only -- for elements behind "
        "clicks (drawers, modals), read the component source or use a throwaway probe."
    )
    return 0
