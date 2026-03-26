"""
SportsCaster Pro - Camera Sources Router v9
Classifies cameras as integrated vs external USB.
"""
import logging, os, re, subprocess, shutil
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.db import get_conn
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.cameras")


class CameraSource(BaseModel):
    label: str
    url:   str
    type:  str = "ip"   # integrated | usb | ip | mobile | rtsp


def _classify(name: str, idx: int) -> str:
    n = name.lower()
    if any(k in n for k in ["integrated","built-in","builtin","internal",
                              "facetime","isight","front","laptop"]):
        return "integrated"
    return "usb"


def _list_dshow():
    try:
        r = subprocess.run(["ffmpeg","-list_devices","true","-f","dshow","-i","dummy"],
                           capture_output=True,text=True,timeout=10)
        return re.findall(r'"([^"]+)"\s*\(video\)', r.stderr, re.IGNORECASE)
    except Exception:
        return []


def _list_v4l2():
    import glob
    result = []
    for dev in sorted(glob.glob("/dev/video*")):
        idx  = dev.replace("/dev/video","")
        name = f"Camera {idx}"
        try:
            r = subprocess.run(["v4l2-ctl","--device",dev,"--info"],
                               capture_output=True,text=True,timeout=3)
            for line in r.stdout.splitlines():
                if "Card type" in line:
                    name = line.split(":")[-1].strip(); break
        except Exception: pass
        result.append({"index":idx,"name":name,"url":idx,"device":dev,
                        "type":_classify(name, int(idx) if idx.isdigit() else 0)})
    return result


@router.get("/")
async def list_cameras():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM camera_sources ORDER BY id").fetchall()
    conn.close()
    return {"cameras": [dict(r) for r in rows]}


@router.get("/detect")
async def detect_cameras():
    """Return cameras grouped by type: integrated, usb, saved IP cameras."""
    integrated, usb_cams, all_cams = [], [], []

    if os.name == "nt":
        devices = _list_dshow()
        for i, name in enumerate(devices):
            t   = _classify(name, i)
            cam = {"index":i,"label":name,"url":str(i),"type":t,"os":"windows"}
            (integrated if t=="integrated" else usb_cams).append(cam)
            all_cams.append(cam)
        if not devices:
            cam = {"index":0,"label":"Default Camera","url":"0","type":"usb","os":"windows"}
            usb_cams.append(cam); all_cams.append(cam)
    else:
        devs = _list_v4l2()
        for d in devs:
            cam = {"index":d["index"],"label":d["name"],"url":d["url"],"type":d["type"],"os":"linux"}
            (integrated if d["type"]=="integrated" else usb_cams).append(cam)
            all_cams.append(cam)
        if not devs:
            cam = {"index":"0","label":"USB Camera 0","url":"0","type":"usb","os":"linux"}
            usb_cams.append(cam); all_cams.append(cam)

    # Saved IP / mobile cameras from DB
    conn = get_conn()
    saved = conn.execute("SELECT * FROM camera_sources WHERE type IN ('ip','mobile','rtsp') ORDER BY id").fetchall()
    conn.close()
    for r in saved:
        cam = {"index":f"saved_{r['id']}","label":r["label"],"url":r["url"],"type":r["type"],"os":"any"}
        all_cams.append(cam)

    return {
        "integrated": integrated,
        "usb":        usb_cams,
        "all":        all_cams,
        "platform":   "windows" if os.name=="nt" else "linux",
    }


@router.post("/")
async def add_camera(cam: CameraSource, request: Request):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO camera_sources (label,url,type) VALUES (?,?,?)",
                           (cam.label, cam.url, cam.type))
        conn.commit(); new_id = cur.lastrowid
    except Exception as e:
        conn.close(); raise HTTPException(400, str(e))
    conn.close()
    return {"id": new_id, "label": cam.label, "url": cam.url}


@router.delete("/{cam_id}")
async def delete_camera(cam_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM camera_sources WHERE id=?", (cam_id,))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/{cam_id}/activate")
async def activate_camera(cam_id: int, request: Request):
    conn = get_conn()
    row = conn.execute("SELECT * FROM camera_sources WHERE id=?", (cam_id,)).fetchone()
    if not row: conn.close(); raise HTTPException(404, "Camera not found")
    conn.execute("UPDATE camera_sources SET active=0")
    conn.execute("UPDATE camera_sources SET active=1 WHERE id=?", (cam_id,))
    conn.commit(); conn.close()
    url = row["url"]
    app_state["camera_source"] = url
    try:
        await request.app.state.manager.send_event("CAMERA_CHANGED",
            {"url":url,"label":row["label"],"type":row["type"]})
    except: pass
    return {"ok":True,"url":url,"label":row["label"]}


@router.post("/activate-url")
async def activate_by_url(url: str, label: str = "", request: Request = None):
    app_state["camera_source"] = url
    try:
        if request:
            await request.app.state.manager.send_event("CAMERA_CHANGED", {"url":url,"label":label})
    except: pass
    return {"ok":True,"url":url}


@router.get("/active")
async def get_active():
    conn = get_conn()
    row = conn.execute("SELECT * FROM camera_sources WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"url":app_state.get("camera_source","0"),"label":"Default","type":"usb"}
    return dict(row)


@router.get("/all-active")
async def get_all_active():
    """Return all active sources including in-memory state."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM camera_sources WHERE active=1").fetchall()
    conn.close()
    cameras = [dict(r) for r in rows]
    # Add in-memory state camera if not already in list
    current = app_state.get("camera_source","")
    if current and not any(c["url"]==current for c in cameras):
        cameras.append({"url":current,"label":"Active Camera","type":"usb","active":1})
    return {"cameras": cameras}


@router.post("/test")
async def test_camera(url: str):
    """Quick camera test without CV2 dependency."""
    from routers.streaming import _resolve_camera_input
    args = _resolve_camera_input(url, 15, "640x480")
    cmd  = ["ffmpeg"] + args + ["-frames:v","2","-f","null","-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"ok": r.returncode==0, "url": url, "output": (r.stdout+r.stderr)[-400:]}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


@router.get("/detect-usb")
async def detect_usb():
    return await detect_cameras()


@router.get("/storage")
async def get_storage():
    recordings_path = os.path.abspath("../recordings")
    os.makedirs(recordings_path, exist_ok=True)
    try:
        u = shutil.disk_usage(recordings_path)
        total_gb = round(u.total/1e9, 1)
        free_gb  = round(u.free /1e9, 1)
        used_gb  = round(u.used /1e9, 1)
        warning  = free_gb < 5.0
        return {"total_gb":total_gb,"used_gb":used_gb,"free_gb":free_gb,
                "warning":warning,
                "message":f"⚠ Low disk: {free_gb}GB remaining" if warning else f"{free_gb}GB free"}
    except Exception as e:
        return {"total_gb":0,"used_gb":0,"free_gb":0,"warning":False,"error":str(e)}
