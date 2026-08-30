"""Demo target app for cc-visual-walkthrough: a tiny FastAPI + htmx
notes application with a login form, CRUD, and one deliberately slow
async operation ("analyze") whose progress state exists so the
walkthrough's progress-capture has something real to record.

Run:  uv run uvicorn demo.app:app --port 8123
Login: demo / demo123 (a throwaway demo account, hardcoded on purpose).

This is a demonstration fixture, not an example of production auth.
"""

from __future__ import annotations

import asyncio
import html
import sqlite3
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ccwalk demo app")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

_DB_PATH = Path(tempfile.gettempdir()) / f"ccwalk_demo_{time.time_ns()}.db"
_db = sqlite3.connect(_DB_PATH, check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT NOT NULL)")
_db.execute(
    "CREATE TABLE IF NOT EXISTS analyses (note_id INTEGER PRIMARY KEY, "
    "progress INTEGER NOT NULL, result TEXT)"
)
_db.commit()

USERNAME, PASSWORD = "demo", "demo123"
COOKIE = "demo_session"

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>ccwalk demo — Notes</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="/static/htmx.min.js"></script>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background:#f5f6f8;
         color:#1c2330; max-width:640px; margin:0 auto; padding:24px; }}
  h1 {{ font-size:1.4em; }}
  .card {{ background:#fff; border:1px solid #dde1e8; border-radius:10px;
           padding:16px 20px; margin:12px 0; }}
  input[type=text], input[type=password] {{ padding:8px 10px; border:1px solid #c6ccd6;
           border-radius:6px; width:60%; }}
  button {{ padding:8px 14px; border:0; border-radius:6px; background:#2f6fed;
            color:#fff; cursor:pointer; }}
  button.danger {{ background:#d64545; }}
  .note {{ display:flex; align-items:center; gap:10px; justify-content:space-between; }}
  .progress {{ color:#a05a00; font-style:italic; }}
  .result {{ color:#1e7d3c; }}
  .err {{ color:#d64545; }}
</style></head>
<body>
{body}
</body></html>"""


def _logged_in(request: Request) -> bool:
    return request.cookies.get(COOKIE) == "ok"


def _note_row(note_id: int, text: str) -> str:
    analysis = _db.execute(
        "SELECT progress, result FROM analyses WHERE note_id = ?", (note_id,)
    ).fetchone()
    return f"""
    <div class="card note" data-testid="note-{note_id}">
      <span data-testid="note-text">{html.escape(text)}</span>
      <span>
        <button data-testid="analyze-{note_id}" hx-post="/notes/{note_id}/analyze"
                hx-target="#analysis-{note_id}" hx-swap="innerHTML">Analyze</button>
        <button class="danger" data-testid="delete-{note_id}" hx-delete="/notes/{note_id}"
                hx-target="#notes-list" hx-swap="outerHTML">Delete</button>
      </span>
    </div>
    <div id="analysis-{note_id}" data-testid="analysis-slot-{note_id}">{_analysis_fragment(note_id, analysis) if analysis else ''}</div>
    """


def _analysis_fragment(note_id: int, row) -> str:
    progress, result = row
    if result:
        return (
            f'<div class="card result" data-testid="analysis-result">'
            f"Analysis: {html.escape(result)}</div>"
        )
    return (
        f'<div class="card progress" data-testid="analysis-progress" '
        f'hx-get="/notes/{note_id}/analysis" hx-trigger="every 500ms" '
        f'hx-swap="outerHTML">Analyzing… step {progress}/4</div>'
    )


def _notes_list() -> str:
    rows = _db.execute("SELECT id, text FROM notes ORDER BY id").fetchall()
    items = "".join(_note_row(i, t) for i, t in rows) or (
        '<p data-testid="empty-state">No notes yet — add one above.</p>'
    )
    return f'<div id="notes-list" data-testid="notes-list">{items}</div>'


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    body = f"""
    <h1 data-testid="app-title">Notes</h1>
    <div class="card">
      <form hx-post="/notes" hx-target="#notes-list" hx-swap="outerHTML"
            data-testid="note-form">
        <input type="text" name="text" placeholder="Write a note…" required
               data-testid="note-input">
        <button type="submit" data-testid="note-add">Add</button>
      </form>
    </div>
    {_notes_list()}
    <p><a href="/logout" data-testid="logout">Log out</a></p>
    """
    return HTMLResponse(_PAGE.format(body=body))


@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = ""):
    err = '<p class="err" data-testid="login-error">Wrong credentials.</p>' if error else ""
    body = f"""
    <h1 data-testid="login-title">Sign in</h1>
    <div class="card">
      {err}
      <form method="post" action="/login" data-testid="login-form">
        <p><input type="text" name="username" placeholder="Username" data-testid="login-user"></p>
        <p><input type="password" name="password" placeholder="Password" data-testid="login-pass"></p>
        <button type="submit" data-testid="login-submit">Sign in</button>
      </form>
    </div>
    """
    return HTMLResponse(_PAGE.format(body=body))


@app.post("/login")
def login(username: str = Form(""), password: str = Form("")):
    if username == USERNAME and password == PASSWORD:
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(COOKIE, "ok", httponly=True)
        return resp
    return RedirectResponse("/login?error=1", status_code=302)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/notes", response_class=HTMLResponse)
def create_note(text: str = Form(...)):
    _db.execute("INSERT INTO notes (text) VALUES (?)", (text,))
    _db.commit()
    return HTMLResponse(_notes_list())


@app.delete("/notes/{note_id}", response_class=HTMLResponse)
def delete_note(note_id: int):
    _db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    _db.execute("DELETE FROM analyses WHERE note_id = ?", (note_id,))
    _db.commit()
    return HTMLResponse(_notes_list())


async def _run_analysis(note_id: int) -> None:
    for step in range(1, 5):
        _db.execute(
            "INSERT INTO analyses (note_id, progress, result) VALUES (?, ?, NULL) "
            "ON CONFLICT(note_id) DO UPDATE SET progress = ?",
            (note_id, step, step),
        )
        _db.commit()
        await asyncio.sleep(1.0)
    row = _db.execute("SELECT text FROM notes WHERE id = ?", (note_id,)).fetchone()
    words = len((row[0] if row else "").split())
    _db.execute(
        "UPDATE analyses SET result = ? WHERE note_id = ?",
        (f"{words} words, sentiment: positive, 0 issues found", note_id),
    )
    _db.commit()


@app.post("/notes/{note_id}/analyze", response_class=HTMLResponse)
async def analyze(note_id: int):
    _db.execute(
        "INSERT INTO analyses (note_id, progress, result) VALUES (?, 0, NULL) "
        "ON CONFLICT(note_id) DO UPDATE SET progress = 0, result = NULL",
        (note_id,),
    )
    _db.commit()
    asyncio.get_event_loop().create_task(_run_analysis(note_id))
    row = _db.execute(
        "SELECT progress, result FROM analyses WHERE note_id = ?", (note_id,)
    ).fetchone()
    return HTMLResponse(_analysis_fragment(note_id, row))


@app.get("/notes/{note_id}/analysis", response_class=HTMLResponse)
def analysis_status(note_id: int):
    row = _db.execute(
        "SELECT progress, result FROM analyses WHERE note_id = ?", (note_id,)
    ).fetchone()
    if row is None:
        return HTMLResponse("")
    return HTMLResponse(_analysis_fragment(note_id, row))
