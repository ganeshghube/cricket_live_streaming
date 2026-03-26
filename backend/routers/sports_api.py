"""
SportsCaster Pro - Multi-sport state API
Provides /api/{sport}/state endpoints for football, hockey, volleyball, custom.
Each persists state to SQLite and broadcasts via WebSocket.
"""
import json, logging
from datetime import datetime
from fastapi import APIRouter, Request
from services.db import get_conn
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.sports")

SPORTS = ["football", "hockey", "volleyball", "custom"]


def _ensure_tables():
    conn = get_conn()
    for sport in SPORTS:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {sport}_state (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL DEFAULT '{{}}',
            updated_at TEXT DEFAULT (datetime('now'))
        )""")
    conn.commit()
    conn.close()

_ensure_tables()


def _get_state(sport: str) -> dict:
    conn = get_conn()
    row = conn.execute(f"SELECT data FROM {sport}_state WHERE id=1").fetchone()
    conn.close()
    if row:
        try: return json.loads(row["data"])
        except: return {}
    return {}


def _set_state(sport: str, data: dict):
    conn = get_conn()
    conn.execute(
        f"INSERT OR REPLACE INTO {sport}_state (id,data,updated_at) VALUES (1,?,?)",
        (json.dumps(data), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


# ── Football ──────────────────────────────────────────────────────────────
@router.get("/football/state")
async def get_football():
    return _get_state("football")

@router.post("/football/state")
async def post_football(payload: dict, request: Request):
    _set_state("football", payload)
    app_state["score"] = payload
    app_state["active_sport"] = "football"
    try: await request.app.state.manager.send_event("SCORE_UPDATE", {"state": payload, "sport": "football"})
    except: pass
    return {"ok": True}

# ── Hockey ────────────────────────────────────────────────────────────────
@router.get("/hockey/state")
async def get_hockey():
    return _get_state("hockey")

@router.post("/hockey/state")
async def post_hockey(payload: dict, request: Request):
    _set_state("hockey", payload)
    app_state["score"] = payload
    app_state["active_sport"] = "hockey"
    try: await request.app.state.manager.send_event("SCORE_UPDATE", {"state": payload, "sport": "hockey"})
    except: pass
    return {"ok": True}

# ── Volleyball ────────────────────────────────────────────────────────────
@router.get("/volleyball/state")
async def get_volleyball():
    return _get_state("volleyball")

@router.post("/volleyball/state")
async def post_volleyball(payload: dict, request: Request):
    _set_state("volleyball", payload)
    app_state["score"] = payload
    app_state["active_sport"] = "volleyball"
    try: await request.app.state.manager.send_event("SCORE_UPDATE", {"state": payload, "sport": "volleyball"})
    except: pass
    return {"ok": True}

# ── Custom ────────────────────────────────────────────────────────────────
@router.get("/custom/state")
async def get_custom():
    return _get_state("custom")

@router.post("/custom/state")
async def post_custom(payload: dict, request: Request):
    _set_state("custom", payload)
    app_state["score"] = payload
    app_state["active_sport"] = "custom"
    try: await request.app.state.manager.send_event("SCORE_UPDATE", {"state": payload, "sport": "custom"})
    except: pass
    return {"ok": True}
