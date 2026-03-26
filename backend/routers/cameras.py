"""
SportsCaster Pro - Camera Sources Router (v5)
Fixed: Windows dshow device listing, Linux v4l2, storage info, camera dropdown.
"""
import logging, os, re, subprocess
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from services.db import get_conn
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.cameras")


class CameraSource(BaseModel):
    label: str
    url: str
    type: str = "ip"


def _list_dshow() -> list:
    """Windows: list DirectShow video devices."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=8
        )
        return re.findall(r'"([^"]+)"\s*\(video\)', r.stderr, re.IGNORECASE)
    except Exception:
        return []


def _list_v4l2() -> list:
    """Linux/Pi: list /dev/video* devices."""
    import glob
    devs = sorted(glob.glob("/dev/video*"))
    result = []
    for dev in devs:
        idx = dev.replace("/dev/video", "")
        try:
            r = subprocess.run(["v4l2-ctl", "--device", dev, "--info"],
                               capture_output=True, text=True, timeout=3)
            name = "USB Camera"
            for line in r.stdout.splitlines():
                if "Card type" in line:
                    name = line.split(":")[-1].strip()
                    break
            result.append({"index": idx, "label": name, "url": idx, "device": dev})
        except Exception:
            result.append({"index": idx, "label": f"Camera {idx}", "url": idx, "device": dev})
    return result


@router.get("/")
async def list_cameras():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM camera_sources ORDER BY id").fetchall()
    conn.close()
    return {"cameras": [dict(r) for r in rows]}


@router.get("/detect")
async def detect_cameras():
    """Auto-detect all available cameras for the dropdown."""
    cameras = []
    if os.name == "nt":
        # Windows DirectShow
        devices = _list_dshow()
        for i, name in enumerate(devices):
            cameras.append({"index": i, "label": name, "url": str(i), "type": "usb", "os": "windows"})
        if not devices:
            cameras.append({"index": 0, "label": "Default Camera", "url": "0", "type": "usb", "os": "windows"})
    else:
        # Linux/Pi v4l2
        devs = _list_v4l2()
        for d in devs:
            cameras.append({"index": d["index"], "label": d["label"], "url": d["url"], "type": "usb", "os": "linux"})
        if not devs:
            cameras.append({"index": 0, "label": "USB Camera 0", "url": "0", "type": "usb", "os": "linux"})

    # Add common IP camera options
    cameras.append({"index": "ip", "label": "IP Camera (RTSP/HTTP)", "url": "", "type": "ip", "os": "any"})
    cameras.append({"index": "mobile", "label": "Mobile (IP Webcam App)", "url": "http://192.168.4.2:8080/video", "type": "mobile", "os": "any"})

    # Add saved IP cameras from DB
    conn = get_conn()
    rows = conn.execute("SELECT * FROM camera_sources WHERE type IN ('ip','mobile') ORDER BY id").fetchall()
    conn.close()
    for r in rows:
        cameras.append({"index": f"saved_{r['id']}", "label": r["label"], "url": r["url"], "type": r["type"], "os": "any"})

    return {"cameras": cameras, "platform": "windows" if os.name == "nt" else "linux"}


@router.post("/")
async def add_camera(cam: CameraSource, request: Request):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO camera_sources (label,url,type) VALUES (?,?,?)",
                           (cam.label, cam.url, cam.type))
        conn.commit()
        new_id = cur.lastrowid
    except Exception as e:
        conn.close()
        raise HTTPException(400, f"Camera error: {e}")
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
        await request.app.state.manager.send_event("CAMERA_CHANGED", {"url": url, "label": row["label"]})
    except: pass
    return {"ok": True, "url": url, "label": row["label"]}


@router.post("/activate-url")
async def activate_by_url(url: str, request: Request):
    """Activate camera by URL string directly (for dropdown selection)."""
    app_state["camera_source"] = url
    try:
        await request.app.state.manager.send_event("CAMERA_CHANGED", {"url": url})
    except: pass
    return {"ok": True, "url": url}


@router.get("/active")
async def get_active():
    conn = get_conn()
    row = conn.execute("SELECT * FROM camera_sources WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"url": app_state.get("camera_source", "0"), "label": "Default"}
    return dict(row)


@router.get("/detect-usb")
async def detect_usb():
    return await detect_cameras()


@router.post("/test")
async def test_camera(url: str):
    import cv2
    try:
        cap = cv2.VideoCapture(url if url.startswith("http") else int(url))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret, _ = cap.read()
        cap.release()
        return {"ok": ret, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/storage")
async def get_storage():
    """Return disk space info for recording tab."""
    import shutil
    recordings_path = os.path.abspath("../recordings")
    os.makedirs(recordings_path, exist_ok=True)
    try:
        usage = shutil.disk_usage(recordings_path)
        total_gb  = round(usage.total / 1e9, 1)
        free_gb   = round(usage.free  / 1e9, 1)
        used_gb   = round(usage.used  / 1e9, 1)
        warning   = free_gb < 5.0
        return {
            "total_gb": total_gb,
            "used_gb":  used_gb,
            "free_gb":  free_gb,
            "warning":  warning,
            "message":  f"⚠ Low disk space: {free_gb}GB remaining" if warning else f"{free_gb}GB free"
        }
    except Exception as e:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "warning": False, "error": str(e)}
