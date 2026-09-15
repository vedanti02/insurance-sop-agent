"""FastAPI surface. Session state lives server-side; the UI only ever sees masked views."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import audit
from .config import PROJECT_DIR, load_settings
from .session import SessionManager
from .tools.insurance import OUTBOX

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
settings = load_settings()
manager = SessionManager(settings)
app = FastAPI(title="Insurance Claims SOP Agent")


class CreateSession(BaseModel):
    vertical: str | None = None
    consent_scenario: str | None = None
    demo_today: str | None = None


class SendMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": settings.llm_mode, "vertical": settings.vertical,
            "demo_today": settings.demo_today.isoformat()}


@app.post("/api/sessions")
def create_session(body: CreateSession, x_api_key: str | None = Header(default=None)) -> dict:
    sess = manager.create(body.vertical, body.consent_scenario, x_api_key, body.demo_today)
    return _view(sess)


def _view(sess) -> dict:
    return {"session_id": sess.bb.session_id, "mode": sess.mode, "vertical": sess.bb.vertical,
            "required_fields": sess.ctx.policy.verification.required_fields, "state": sess.bb.public_view()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    sess = manager.get(session_id)
    if not sess:
        raise HTTPException(404, "no such session")
    return _view(sess)


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessage) -> dict:
    sess = manager.get(session_id)
    if not sess:
        raise HTTPException(404, "no such session")
    phase_before = sess.bb.phase
    result = sess.turn(body.text)
    audit.record(sess.bb, phase_before, result.transitions,
                 {"perceive": sess.ctx.settings.perceive_model, "respond": sess.ctx.settings.respond_model, "mode": sess.mode})
    return {"reply": result.reply, "phase": result.phase, "transitions": result.transitions,
            "trace": result.trace, "state": sess.bb.public_view()}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    """Purge: drops server-side state and the session's audit lines."""
    return {"deleted": manager.delete(session_id), "audit_lines_removed": audit.purge(session_id)}


@app.get("/api/verticals")
def list_verticals() -> dict:
    from . import verticals
    return {"verticals": [{"name": n, "domain": verticals.get(n).PROMPT_VARS["domain"], "scripts": verticals.get(n).SCRIPTS}
                          for n in verticals.names()], "default": settings.vertical}


@app.get("/api/outbox")
def outbox() -> dict:
    from .tools.card import LEDGER
    return {"emails": [{k: v for k, v in e.items() if k != "to"} for e in OUTBOX], "credits": list(LEDGER)}


_dist = PROJECT_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = _dist / path
        return FileResponse(target if path and target.is_file() else _dist / "index.html")
