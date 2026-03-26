"""
SportsCaster Pro - Cricket Dedicated API Router
Provides clean /api/match, /api/squads, /api/ui, /api/undo endpoints
as requested — backed by SQLite, no Firebase.

These endpoints are used by:
  - cricket_admin.html  (scoring admin)
  - overlay/index.html  (polls every 300ms for live update)
"""

import json, logging, time
from datetime import datetime
from fastapi import APIRouter, Request

from services.db import get_conn
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.cricket_api")

# ── Helpers ───────────────────────────────────────────────────────────────
def _row_or_default(table: str, default: dict) -> dict:
    conn = get_conn()
    row = conn.execute(f"SELECT data FROM {table} WHERE id=1").fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["data"])
        except Exception:
            return default
    return default


def _upsert(table: str, data: dict):
    conn = get_conn()
    conn.execute(
        f"INSERT OR REPLACE INTO {table} (id, data, updated_at) VALUES (1, ?, ?)",
        (json.dumps(data), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def _ensure_tables():
    """Create cricket-specific tables if they don't exist."""
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS match_state (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS squads_data (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ui_state (
        id INTEGER PRIMARY KEY,
        data TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS undo_stack (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT NOT NULL,
        label TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    # Seed ui_state — always ensure scorebar defaults to True
    conn.execute(
        "INSERT OR IGNORE INTO ui_state (id,data) VALUES (1,?)",
        (json.dumps({"scorebar": True, "scorecard": False}),)
    )
    # Also fix any corrupted ui_state where scorebar might be false
    try:
        row = conn.execute("SELECT data FROM ui_state WHERE id=1").fetchone()
        if row:
            ui = json.loads(row["data"])
            if ui.get("scorebar") is False and ui.get("scorecard") is False:
                # Both false = corrupted state, reset to defaults
                conn.execute("UPDATE ui_state SET data=? WHERE id=1",
                             (json.dumps({"scorebar": True, "scorecard": False}),))
    except Exception:
        pass
    conn.commit()
    conn.close()


_ensure_tables()


# ════════════════════════════════════════════════════════════════════════════
# MATCH STATE — /api/match
# ════════════════════════════════════════════════════════════════════════════

@router.get("/match")
async def get_match():
    """Overlay polls this every 500ms to get live cricket state."""
    data = _row_or_default("match_state", {})
    # Ensure sport field is set so overlay renderData() routes correctly
    if data and "batTeam" in data and "sport" not in data:
        data["sport"] = "cricket"
    return data


@router.post("/match")
async def post_match(payload: dict, request: Request):
    """Admin pushes full match state here on every ball."""
    # Ensure sport is always set
    if "sport" not in payload and ("batTeam" in payload or "runs" in payload):
        payload["sport"] = "cricket"
    _upsert("match_state", payload)
    app_state["score"]        = payload
    app_state["active_sport"] = payload.get("sport", "cricket")
    # Broadcast via WebSocket for instant overlay update
    try:
        await request.app.state.manager.send_event("CRICKET_UPDATE", payload)
    except Exception:
        pass
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# SQUADS — /api/squads
# ════════════════════════════════════════════════════════════════════════════

@router.get("/squads")
async def get_squads():
    return _row_or_default("squads_data", {"sqA": "", "sqB": ""})


@router.post("/squads")
async def post_squads(payload: dict):
    _upsert("squads_data", payload)
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# UI STATE — /api/ui  (scorebar / scorecard visibility)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/ui")
async def get_ui():
    return _row_or_default("ui_state", {"scorebar": True, "scorecard": False})


@router.post("/ui")
async def post_ui(payload: dict, request: Request):
    current = _row_or_default("ui_state", {"scorebar": True, "scorecard": False})
    current.update(payload)
    _upsert("ui_state", current)
    # Broadcast so overlay iframe updates without full poll cycle
    try:
        await request.app.state.manager.send_event("UI_UPDATE", current)
    except Exception:
        pass
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# UNDO STACK — /api/undo
# Keeps last 5 snapshots only (server-enforced)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/undo")
async def get_undo():
    """Return count and top label for badge."""
    conn = get_conn()
    rows = conn.execute("SELECT id, label FROM undo_stack ORDER BY id DESC LIMIT 5").fetchall()
    conn.close()
    return {
        "count": len(rows),
        "snapshots": [{"id": r["id"], "label": r["label"]} for r in rows]
    }


@router.post("/undo")
async def push_undo(payload: dict):
    """Push a state snapshot. Prunes to keep only last 5."""
    label = payload.get("label", "")
    data  = payload.get("state", payload)

    conn = get_conn()
    conn.execute("INSERT INTO undo_stack (data, label) VALUES (?,?)",
                 (json.dumps(data), label))
    conn.commit()

    # Prune — keep only last 5
    rows = conn.execute("SELECT id FROM undo_stack ORDER BY id DESC").fetchall()
    if len(rows) > 5:
        ids_to_delete = [r["id"] for r in rows[5:]]
        conn.execute(f"DELETE FROM undo_stack WHERE id IN ({','.join('?'*len(ids_to_delete))})",
                     ids_to_delete)
        conn.commit()

    count = conn.execute("SELECT COUNT(*) as c FROM undo_stack").fetchone()["c"]
    conn.close()
    return {"ok": True, "count": count}


@router.delete("/undo")
async def pop_undo():
    """Pop the most recent snapshot and return it."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM undo_stack ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "Nothing to undo"}

    state = json.loads(row["data"])
    conn.execute("DELETE FROM undo_stack WHERE id=?", (row["id"],))
    conn.commit()
    count = conn.execute("SELECT COUNT(*) as c FROM undo_stack").fetchone()["c"]
    conn.close()
    return {"ok": True, "state": state, "count": count}


@router.delete("/undo/all")
async def clear_undo():
    """Clear entire undo stack (on new match / innings swap)."""
    conn = get_conn()
    conn.execute("DELETE FROM undo_stack")
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# CONVENIENCE ALIASES — keep old cricket_admin.html endpoints working
# ════════════════════════════════════════════════════════════════════════════

@router.post("/scoring/cricket/state")
async def compat_cricket_state(payload: dict, request: Request):
    """Backward compat for old cricket_admin calls."""
    return await post_match(payload, request)


@router.post("/scoring/cricket/reset")
async def compat_cricket_reset(request: Request):
    _upsert("match_state", {})
    conn = get_conn()
    conn.execute("DELETE FROM undo_stack")
    conn.commit()
    conn.close()
    app_state["score"] = {}
    try:
        await request.app.state.manager.send_event("CRICKET_UPDATE", {"reset": True})
    except Exception:
        pass
    return {"ok": True}


@router.get("/scoring/cricket/state")
async def compat_get_cricket_state():
    return _row_or_default("match_state", {})
