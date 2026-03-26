"""
SportsCaster Pro v2 - Scoring Router
Cricket, Football, Hockey, Volleyball, Custom.
"""

import json, logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any

from services.db import get_conn
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.scoring")


class NewMatchRequest(BaseModel):
    sport: str
    team_a: str
    team_b: str
    overs: Optional[int] = 20
    players_a: Optional[list] = []
    players_b: Optional[list] = []


class ScoreEventRequest(BaseModel):
    match_id: int
    event: str
    payload: Optional[Dict[str, Any]] = {}


class PlayerSelectRequest(BaseModel):
    match_id: int
    role: str
    player_name: str


# ── State factories ────────────────────────────────────────────────────────

def _cricket(req):
    return {
        "sport": "cricket", "team_a": req.team_a, "team_b": req.team_b,
        "players_a": req.players_a, "players_b": req.players_b,
        "batting_team": "a", "innings": 1, "total_overs": req.overs,
        "score": {
            "a": {"runs":0,"wickets":0,"overs":0,"balls":0,"extras":0},
            "b": {"runs":0,"wickets":0,"overs":0,"balls":0,"extras":0},
        },
        "current_over": [], "over_history": [],
        "striker": "", "non_striker": "", "bowler": "",
        "partnerships": [], "current_partnership": {"runs":0,"balls":0},
        "last_event": None,
    }

def _football(req):
    return {
        "sport": "football", "team_a": req.team_a, "team_b": req.team_b,
        "score": {"a":0,"b":0}, "half": 1, "timer_seconds": 0,
        "cards": {"a":{"yellow":0,"red":0},"b":{"yellow":0,"red":0}},
        "substitutions": {"a":[],"b":[]}, "events": [], "last_event": None,
    }

def _hockey(req):
    return {
        "sport": "hockey", "team_a": req.team_a, "team_b": req.team_b,
        "score": {"a":0,"b":0}, "quarter": 1,
        "penalty_corners": {"a":0,"b":0},
        "cards": {"a":{"green":0,"yellow":0,"red":0},"b":{"green":0,"yellow":0,"red":0}},
        "events": [], "last_event": None,
    }

def _volleyball(req):
    return {
        "sport": "volleyball", "team_a": req.team_a, "team_b": req.team_b,
        "current_set": 1, "set_scores": [{"a":0,"b":0}],
        "sets_won": {"a":0,"b":0}, "timeouts": {"a":2,"b":2},
        "last_event": None,
    }

def _custom(req):
    return {
        "sport": "custom", "team_a": req.team_a, "team_b": req.team_b,
        "score": {"a":0,"b":0}, "last_event": None,
    }

FACTORIES = {"cricket":_cricket,"football":_football,"hockey":_hockey,"volleyball":_volleyball,"custom":_custom}


# ── Event processors ───────────────────────────────────────────────────────

def _proc_cricket(state, event, payload):
    bt = state["batting_team"]
    sc = state["score"][bt]
    popup = None

    if event.startswith("run_"):
        runs = int(event.split("_")[1])
        sc["runs"] += runs; sc["balls"] += 1
        state["current_over"].append(str(runs))
        state["current_partnership"]["runs"] += runs
        state["current_partnership"]["balls"] += 1
        if runs == 4: popup = "FOUR! 🏏"
        elif runs == 6: popup = "SIX! 🏏"
    elif event == "wicket":
        sc["wickets"] += 1; sc["balls"] += 1
        state["current_over"].append("W")
        state["partnerships"].append(dict(state["current_partnership"]))
        state["current_partnership"] = {"runs":0,"balls":0}
        popup = "WICKET! 🎯"
    elif event == "wide":
        sc["runs"] += 1; sc["extras"] += 1
        state["current_over"].append("Wd")
    elif event == "no_ball":
        sc["runs"] += 1; sc["extras"] += 1
        state["current_over"].append("NB")
    elif event in ("bye","leg_bye"):
        r = payload.get("runs", 1)
        sc["runs"] += r; sc["extras"] += r; sc["balls"] += 1
        state["current_over"].append(f"B{r}")

    legal = [e for e in state["current_over"] if e not in ("Wd","NB")]
    if len(legal) >= 6:
        sc["overs"] += 1
        state["over_history"].append(list(state["current_over"]))
        state["current_over"] = []
        state["striker"], state["non_striker"] = state["non_striker"], state["striker"]

    state["last_event"] = {"event": event, "popup": popup}
    return state

def _proc_football(state, event, payload):
    popup = None
    if event == "goal_a": state["score"]["a"] += 1; popup = f"⚽ GOAL! {state['team_a']}"
    elif event == "goal_b": state["score"]["b"] += 1; popup = f"⚽ GOAL! {state['team_b']}"
    elif event == "yellow_a": state["cards"]["a"]["yellow"] += 1; popup = f"🟡 Yellow — {state['team_a']}"
    elif event == "yellow_b": state["cards"]["b"]["yellow"] += 1; popup = f"🟡 Yellow — {state['team_b']}"
    elif event == "red_a": state["cards"]["a"]["red"] += 1; popup = f"🟥 Red — {state['team_a']}"
    elif event == "red_b": state["cards"]["b"]["red"] += 1; popup = f"🟥 Red — {state['team_b']}"
    elif event == "half": state["half"] = 2; state["timer_seconds"] = 0; popup = "HALF TIME"
    state["last_event"] = {"event": event, "popup": popup}
    return state

def _proc_hockey(state, event, payload):
    popup = None
    if event == "goal_a": state["score"]["a"] += 1; popup = f"🥅 GOAL! {state['team_a']}"
    elif event == "goal_b": state["score"]["b"] += 1; popup = f"🥅 GOAL! {state['team_b']}"
    elif event == "pc_a": state["penalty_corners"]["a"] += 1; popup = "PENALTY CORNER"
    elif event == "pc_b": state["penalty_corners"]["b"] += 1; popup = "PENALTY CORNER"
    elif event == "next_quarter": state["quarter"] = min(state["quarter"] + 1, 4)
    state["last_event"] = {"event": event, "popup": popup}
    return state

def _proc_volleyball(state, event, payload):
    popup = None
    cur = state["set_scores"][state["current_set"] - 1]
    if event == "point_a": cur["a"] += 1
    elif event == "point_b": cur["b"] += 1
    elif event == "timeout_a" and state["timeouts"]["a"] > 0:
        state["timeouts"]["a"] -= 1; popup = f"⏸ Timeout — {state['team_a']}"
    elif event == "timeout_b" and state["timeouts"]["b"] > 0:
        state["timeouts"]["b"] -= 1; popup = f"⏸ Timeout — {state['team_b']}"
    elif event == "set_over":
        winner = "a" if cur["a"] > cur["b"] else "b"
        state["sets_won"][winner] += 1
        state["current_set"] += 1
        state["set_scores"].append({"a":0,"b":0})
        state["timeouts"] = {"a":2,"b":2}
        popup = f"SET WON — {state['team_a'] if winner=='a' else state['team_b']}"
    state["last_event"] = {"event": event, "popup": popup}
    return state

PROCESSORS = {
    "cricket": _proc_cricket, "football": _proc_football,
    "hockey": _proc_hockey, "volleyball": _proc_volleyball,
    "custom": lambda s,e,p: s,
}


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/match/new")
async def new_match(req: NewMatchRequest, request: Request):
    sport = req.sport.lower()
    if sport not in FACTORIES:
        raise HTTPException(400, f"Unsupported sport: {sport}")
    state = FACTORIES[sport](req)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO matches (sport,team_a,team_b,state_json) VALUES (?,?,?,?)",
        (sport, req.team_a, req.team_b, json.dumps(state))
    )
    match_id = cur.lastrowid
    conn.commit(); conn.close()
    state["match_id"] = match_id
    app_state["active_sport"] = sport
    app_state["match_id"] = match_id
    app_state["score"] = state
    try:
        await request.app.state.manager.send_event("MATCH_STARTED", state)
    except Exception: pass
    return {"match_id": match_id, "state": state}


@router.post("/event")
async def score_event(req: ScoreEventRequest, request: Request):
    conn = get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id=?", (req.match_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Match not found")
    state = json.loads(row["state_json"])
    proc = PROCESSORS.get(state["sport"])
    if proc:
        state = proc(state, req.event, req.payload or {})
    conn.execute("UPDATE matches SET state_json=?,updated_at=datetime('now') WHERE id=?",
                 (json.dumps(state), req.match_id))
    conn.execute("INSERT INTO events (match_id,event_type,payload) VALUES (?,?,?)",
                 (req.match_id, req.event, json.dumps(req.payload)))
    conn.commit(); conn.close()
    app_state["score"] = state
    popup = state.get("last_event", {}).get("popup") if state.get("last_event") else None
    app_state["popup"] = popup
    try:
        await request.app.state.manager.send_event("SCORE_UPDATE", {
            "match_id": req.match_id, "state": state, "popup": popup
        })
    except Exception: pass
    return {"state": state}


@router.get("/active")
async def get_active():
    return {"state": app_state.get("score", {})}


@router.get("/matches")
async def list_matches():
    conn = get_conn()
    rows = conn.execute("SELECT id,sport,team_a,team_b,created_at FROM matches ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return {"matches": [dict(r) for r in rows]}


@router.post("/player/select")
async def select_player(req: PlayerSelectRequest, request: Request):
    conn = get_conn()
    row = conn.execute("SELECT * FROM matches WHERE id=?", (req.match_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Match not found")
    state = json.loads(row["state_json"])
    state[req.role] = req.player_name
    conn.execute("UPDATE matches SET state_json=? WHERE id=?", (json.dumps(state), req.match_id))
    conn.commit(); conn.close()
    app_state["score"] = state
    try:
        await request.app.state.manager.send_event("SCORE_UPDATE", {"match_id": req.match_id, "state": state})
    except Exception: pass
    return {"ok": True}


# ─── Cricket direct state push (used by cricket_admin.html) ──────────────

from fastapi import Request as _Req

@router.post("/cricket/state")
async def push_cricket_state(state: dict, request: _Req):
    """
    Receive full cricket match state from cricket_admin.html,
    persist to SQLite, and broadcast to all WS clients (overlay etc).
    """
    import json as _json
    conn = get_conn()

    if state.get("reset"):
        conn.execute("UPDATE matches SET state_json=? WHERE id=(SELECT MAX(id) FROM matches WHERE sport='cricket')",
                     (_json.dumps({}),))
        conn.commit(); conn.close()
        return {"ok": True}

    # Upsert: update latest cricket match or insert new
    row = conn.execute("SELECT id FROM matches WHERE sport='cricket' ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        conn.execute("UPDATE matches SET state_json=?,updated_at=datetime('now') WHERE id=?",
                     (_json.dumps(state), row["id"]))
    else:
        conn.execute("INSERT INTO matches (sport,team_a,team_b,state_json) VALUES ('cricket',?,?,?)",
                     (state.get("batTeam","A"), state.get("bowlTeam","B"), _json.dumps(state)))
    conn.commit(); conn.close()

    app_state["score"]        = state
    app_state["active_sport"] = "cricket"

    try:
        await request.app.state.manager.send_event("CRICKET_UPDATE", state)
    except Exception: pass
    return {"ok": True}


@router.post("/cricket/reset")
async def reset_cricket(request: _Req):
    conn = get_conn()
    conn.execute("DELETE FROM matches WHERE sport='cricket'")
    conn.commit(); conn.close()
    app_state["score"] = {}
    try:
        await request.app.state.manager.send_event("CRICKET_UPDATE", {"sport":"cricket","reset":True})
    except Exception: pass
    return {"ok": True}


@router.get("/cricket/state")
async def get_cricket_state():
    conn = get_conn()
    row = conn.execute("SELECT state_json FROM matches WHERE sport='cricket' ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    import json as _json
    if row:
        return _json.loads(row["state_json"])
    return {}


# ══════════════════════════════════════════════════════════════════════════
# PLAYER MANAGEMENT — save/load players per team (FIX)
# ══════════════════════════════════════════════════════════════════════════

class SavePlayersReq(BaseModel):
    team_name: str
    players: list   # list of strings
    sport: str = "cricket"


@router.post("/players/save")
async def save_players(req: SavePlayersReq):
    """Save player list for a team to DB."""
    conn = get_conn()
    conn.execute("DELETE FROM players WHERE team_name=? AND sport=?", (req.team_name, req.sport))
    for i, name in enumerate(req.players):
        name = str(name).strip()
        if name:
            conn.execute(
                "INSERT OR REPLACE INTO players (team_name,player_name,position,sport) VALUES (?,?,?,?)",
                (req.team_name, name, i, req.sport)
            )
    conn.commit(); conn.close()
    return {"ok": True, "saved": len(req.players)}


@router.get("/players/{team_name}")
async def get_players(team_name: str, sport: str = "cricket"):
    """Load saved players for a team."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT player_name FROM players WHERE team_name=? AND sport=? ORDER BY position",
        (team_name, sport)
    ).fetchall()
    conn.close()
    return {"team": team_name, "players": [r["player_name"] for r in rows]}


@router.get("/players/teams/list")
async def list_teams(sport: str = "cricket"):
    """List all saved team names."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT team_name FROM players WHERE sport=? ORDER BY team_name",
        (sport,)
    ).fetchall()
    conn.close()
    return {"teams": [r["team_name"] for r in rows]}
