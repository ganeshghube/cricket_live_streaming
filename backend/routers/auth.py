"""
SportsCaster Pro - Auth Router
FIX: Session persists across browser refresh via localStorage token + DB-persisted sessions.
"""
import secrets, logging
from fastapi import APIRouter, HTTPException, Response, Request, status
from pydantic import BaseModel
from services.db import get_conn

router = APIRouter()
logger = logging.getLogger("sportscaster.auth")
SESSIONS: dict = {}   # token -> username (also persisted to DB)


def _load_sessions():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT token, username FROM sessions").fetchall()
        conn.close()
        for r in rows:
            SESSIONS[r["token"]] = r["username"]
        logger.info(f"Loaded {len(SESSIONS)} persisted sessions")
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


class LoginReq(BaseModel):
    username: str
    password: str


def get_token(request: Request):
    t = request.cookies.get("session")
    if t: return t
    t = request.headers.get("X-Session-Token")
    if t: return t
    a = request.headers.get("Authorization","")
    if a.startswith("Bearer "): return a[7:]
    return None


def require_auth(request: Request):
    t = get_token(request)
    if not t or t not in SESSIONS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return SESSIONS[t]


@router.post("/login")
async def login(req: LoginReq, response: Response):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                       (req.username, req.password)).fetchone()
    conn.close()
    if not row: raise HTTPException(401, "Invalid credentials")
    token = secrets.token_hex(24)
    SESSIONS[token] = req.username
    _save_session(token, req.username)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=86400*7)
    logger.info(f"Login OK: {req.username}")
    return {"token": token, "username": req.username}


@router.post("/logout")
async def logout(request: Request, response: Response):
    t = get_token(request)
    if t: _del_session(t)
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    t = get_token(request)
    if not t or t not in SESSIONS: raise HTTPException(401, "Not authenticated")
    return {"username": SESSIONS[t], "token": t}


_load_sessions()
