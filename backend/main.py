"""
SportsCaster Pro v6 — v4 base + v5 additions
All v4 features intact. Added: sport admin pages, camera detect, storage API,
AI player/ball detection endpoints, recording disk management.
"""
import asyncio, json, os, logging
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import scoring, streaming, recording, ai_tracking, settings, auth, review, cameras
from routers import cricket_api, sports_api
from services.connection_manager import ConnectionManager
from services.db import init_db
from services.state import app_state

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sportscaster")
manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SportsCaster Pro v6 starting...")
    init_db()
    for d in ["../recordings","../reviews","../models","../training_data",
              "../training_data/ball","../training_data/player","../config"]:
        os.makedirs(d, exist_ok=True)
    app.state.manager = manager
    yield
    logger.info("Shutdown.")

app = FastAPI(title="SportsCaster Pro", version="6.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/auth",      tags=["auth"])
app.include_router(scoring.router,      prefix="/api/scoring",   tags=["scoring"])
app.include_router(streaming.router,    prefix="/api/stream",    tags=["streaming"])
app.include_router(recording.router,    prefix="/api/recording", tags=["recording"])
app.include_router(ai_tracking.router,  prefix="/api/ai",        tags=["ai"])
app.include_router(review.router,       prefix="/api/review",    tags=["review"])
app.include_router(cameras.router,      prefix="/api/cameras",   tags=["cameras"])
app.include_router(settings.router,     prefix="/api/settings",  tags=["settings"])
app.include_router(cricket_api.router,  prefix="/api",           tags=["cricket"])
app.include_router(sports_api.router,   prefix="/api",           tags=["sports"])   # NEW

# ── Static mounts ─────────────────────────────────────────────────────────
for mount, directory in [
    ("/overlay",    "../overlay"),
    ("/recordings", "../recordings"),
    ("/reviews",    "../reviews"),
]:
    os.makedirs(directory, exist_ok=True)
    app.mount(mount, StaticFiles(directory=directory), name=mount.strip("/"))

# Serve /admin/ sport pages  (NEW)
admin_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "admin")
os.makedirs(admin_path, exist_ok=True)
app.mount("/admin", StaticFiles(directory=admin_path, html=True), name="admin")

# Frontend (must be last)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "INIT",
            "payload": {
                "score":            app_state.get("score", {}),
                "stream_status":    app_state.get("stream_status", "idle"),
                "recording_status": app_state.get("recording_status", "idle"),
                "camera_source":    app_state.get("camera_source", ""),
                "active_sport":     app_state.get("active_sport", "cricket"),
                "ui":               app_state.get("ui", {"scorebar":True,"scorecard":False}),
            }
        }))
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            try: msg = json.loads(data)
            except: continue
            mtype = msg.get("type","")

            if mtype == "CRICKET_UPDATE":
                state = msg.get("payload",{})
                if not state.get("reset"):
                    app_state["score"]        = state
                    app_state["active_sport"] = state.get("sport","cricket")
                await manager.broadcast(msg)
            elif mtype == "UI_UPDATE":
                patch = msg.get("payload",{})
                app_state.setdefault("ui",{"scorebar":True,"scorecard":False})
                app_state["ui"].update(patch)
                await manager.broadcast(msg)
            elif mtype == "GET_STATE":
                try:
                    await websocket.send_text(json.dumps({
                        "type":"INIT",
                        "payload":{
                            "score": app_state.get("score",{}),
                            "ui":    app_state.get("ui",{"scorebar":True,"scorecard":False}),
                        }
                    }))
                except: pass
            else:
                await manager.broadcast(msg)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
async def health():
    return {"status":"ok","version":"6.0.0","time":datetime.utcnow().isoformat()}

@app.get("/api/state")
async def get_state():
    return app_state
