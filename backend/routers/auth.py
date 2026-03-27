"""
SportsCaster Pro - Auth Router (Final)
Token returned in JSON, stored in localStorage, sent via X-Session-Token header.
No cookies — works from any IP, any port, no CORS issues.
"""
import secrets, logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.db import get_conn

router = APIRouter()
logger = logging.getLogger("sportscaster.auth")
SESSIONS: dict = {}


def _load_sessions():
    try:
        conn = get_conn()
        for r in conn.execute("SELECT token, username FROM sessions").fetchall():
            SESSIONS[r["token"]] = r["username"]
        conn.close()
        logger.info(f"Loaded {len(SESSIONS)} sessions")
    except Exception:
        pass


def _save_session(token, username):
    try:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO sessions (token,username) VALUES (?,?)", (token, username))
        conn.commit(); conn.close()
    except Exception:
        pass


def _del_session(token):
    SESSIONS.pop(token, None)
    try:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit(); conn.close()
    except Exception:
        pass


def get_token(request: Request):
    t = request.headers.get("X-Session-Token", "").strip()
    if t and t in SESSIONS: return t
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        t = auth[7:].strip()
        if t and t in SESSIONS: return t
    # Also accept cookie for backward compat
    t = request.cookies.get("session", "").strip()
    if t and t in SESSIONS: return t
    return None


def require_auth(request: Request):
    t = get_token(request)
    if not t:
        raise HTTPException(401, "Not authenticated")
    return SESSIONS[t]


class LoginReq(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginReq):
    username = (req.username or "").strip()
    password = (req.password or "").strip()
    if not username or not password:
        raise HTTPException(400, "Username and password required")
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT username FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        conn.close()
    except Exception as e:
        logger.error(f"DB error: {e}")
        raise HTTPException(500, f"Database error: {e}")

    if not row:
        logger.warning(f"Failed login: {username}")
        raise HTTPException(401, "Invalid username or password")

    token = secrets.token_hex(32)
    SESSIONS[token] = username
    _save_session(token, username)
    logger.info(f"Login OK: {username}")
    # Return token in body — frontend stores in localStorage
    return JSONResponse({"ok": True, "token": token, "username": username})


@router.post("/logout")
async def logout(request: Request):
    t = request.headers.get("X-Session-Token", "") or request.cookies.get("session", "")
    if t: _del_session(t)
    return JSONResponse({"ok": True})


@router.get("/me")
async def me(request: Request):
    t = get_token(request)
    if not t: raise HTTPException(401, "Not authenticated")
    return JSONResponse({"ok": True, "username": SESSIONS[t], "token": t})


_load_sessions()
