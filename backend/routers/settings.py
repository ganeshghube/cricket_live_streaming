"""SportsCaster Pro v2 - Settings Router"""
from fastapi import APIRouter
from pydantic import BaseModel
from services.db import get_conn

router = APIRouter()

class SettingsPatch(BaseModel):
    stream_url: str = ""
    stream_key: str = ""
    camera_source: str = "0"
    ai_enabled: str = "false"
    hotspot_ssid: str = "SportsCaster"
    hotspot_pass: str = "broadcast1"

@router.get("/")
async def get_all():
    conn = get_conn()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

@router.post("/")
async def update(patch: SettingsPatch):
    conn = get_conn()
    for k, v in patch.dict().items():
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v))
    conn.commit(); conn.close()
    return {"ok": True}
