"""
SportsCaster Pro - Recording Router v5
Fixed: disk space monitoring, auto-stop when full, MP4 format, proper dshow/v4l2.
"""
import logging, os, shutil, subprocess, time, threading
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.recording")
RECORDINGS_DIR = Path("../recordings")
MAX_RECORDINGS = 50    # v5: keep many more, space-managed not count-managed
MIN_FREE_GB    = 2.0   # auto-stop below 2GB free

_rec_proc:  Optional[subprocess.Popen] = None
_rec_file:  Optional[str]              = None
_watchdog:  Optional[threading.Thread] = None
_stop_watch = threading.Event()


def _free_gb() -> float:
    try:
        return shutil.disk_usage(str(RECORDINGS_DIR)).free / 1e9
    except Exception:
        return 999.0


def _purge_oldest():
    """Delete oldest recordings to free space."""
    files = sorted(RECORDINGS_DIR.glob("**/*.mp4"), key=lambda f: f.stat().st_mtime)
    if files:
        files[0].unlink(missing_ok=True)
        logger.info(f"Purged: {files[0]}")


def _resolve_cam(src: str, output: str) -> list:
    """Build FFmpeg record command matching streaming router's camera handling."""
    if src.startswith("http") or src.startswith("rtsp"):
        return ["ffmpeg", "-i", src,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-movflags", "+faststart", "-y", output]
    if os.name == "nt":
        # Windows: resolve dshow device name
        try:
            import re
            r = subprocess.run(["ffmpeg","-list_devices","true","-f","dshow","-i","dummy"],
                               capture_output=True, text=True, timeout=8)
            devices = re.findall(r'"([^"]+)"\s*\(video\)', r.stderr, re.IGNORECASE)
        except Exception:
            devices = []
        if src.isdigit() and devices:
            dev = devices[min(int(src), len(devices)-1)]
        elif src.startswith("video="):
            dev = src[6:]
        else:
            dev = src
        return ["ffmpeg", "-f", "dshow", "-i", f"video={dev}",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-movflags", "+faststart", "-y", output]
    # Linux/Pi v4l2
    dev = f"/dev/video{src}" if src.isdigit() else src
    return ["ffmpeg", "-f", "v4l2", "-input_format", "mjpeg",
            "-i", dev, "-c:v", "libx264", "-preset", "ultrafast",
            "-movflags", "+faststart", "-y", output]


def _disk_watchdog():
    """Background thread: stop recording if disk < MIN_FREE_GB."""
    global _rec_proc, _rec_file
    while not _stop_watch.is_set():
        time.sleep(5)
        if _rec_proc and _rec_proc.poll() is None:
            free = _free_gb()
            if free < MIN_FREE_GB:
                logger.warning(f"Low disk space ({free:.1f}GB). Stopping recording.")
                _rec_proc.terminate()
                try: _rec_proc.wait(timeout=5)
                except subprocess.TimeoutExpired: _rec_proc.kill()
                _rec_proc = None
                app_state["recording_status"] = "stopped_disk_full"
                app_state["recording_file"] = None


# Start watchdog on import
_watchdog = threading.Thread(target=_disk_watchdog, daemon=True)
_watchdog.start()


@router.post("/start")
async def start_recording(request: Request):
    global _rec_proc, _rec_file
    if _rec_proc and _rec_proc.poll() is None:
        raise HTTPException(409, "Already recording")

    # Check disk space before starting
    free = _free_gb()
    if free < MIN_FREE_GB:
        raise HTTPException(507, f"Insufficient disk space: {free:.1f}GB free (need >{MIN_FREE_GB}GB)")

    # Create dated subfolder
    today = time.strftime("%Y-%m-%d")
    rec_dir = RECORDINGS_DIR / today
    rec_dir.mkdir(parents=True, exist_ok=True)

    # Auto-numbered filename
    existing = list(rec_dir.glob("match_*.mp4"))
    num = len(existing) + 1
    _rec_file = str(rec_dir / f"match_{num:03d}.mp4")

    src = app_state.get("camera_source", "0") or "0"
    cmd = _resolve_cam(src, _rec_file)
    logger.info(f"Record → {_rec_file}  CMD: {' '.join(cmd[:6])}...")

    try:
        _rec_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise HTTPException(500, "FFmpeg not found. Install and add to PATH.")

    app_state["recording_status"] = "recording"
    app_state["recording_file"]   = _rec_file
    app_state["recording_pid"]    = _rec_proc.pid

    try:
        await request.app.state.manager.send_event("RECORDING_STATUS", {
            "status": "recording",
            "file": Path(_rec_file).name,
            "pid": _rec_proc.pid,
            "free_gb": round(free, 1),
        })
    except Exception: pass
    return {"status": "recording", "file": Path(_rec_file).name, "free_gb": round(free,1)}


@router.post("/stop")
async def stop_recording(request: Request):
    global _rec_proc, _rec_file
    if not _rec_proc or _rec_proc.poll() is not None:
        app_state["recording_status"] = "idle"
        try: await request.app.state.manager.send_event("RECORDING_STATUS", {"status":"idle"})
        except Exception: pass
        return {"status":"idle"}

    _rec_proc.terminate()
    try: _rec_proc.wait(timeout=5)
    except subprocess.TimeoutExpired: _rec_proc.kill()

    fname = Path(_rec_file).name if _rec_file else None
    _rec_proc = None; _rec_file = None
    app_state["recording_status"] = "idle"
    app_state["recording_file"]   = None
    app_state["recording_pid"]    = None

    try:
        await request.app.state.manager.send_event("RECORDING_STATUS",
            {"status":"stopped","file":fname})
    except Exception: pass
    return {"status": "stopped", "file": fname}


@router.get("/status")
async def recording_status():
    running = _rec_proc is not None and _rec_proc.poll() is None
    return {
        "status": "recording" if running else app_state.get("recording_status","idle"),
        "file":   Path(_rec_file).name if _rec_file and running else None,
        "free_gb": round(_free_gb(), 1),
    }


@router.get("/list")
async def list_recordings():
    if not RECORDINGS_DIR.exists(): return {"recordings":[]}
    files = sorted(RECORDINGS_DIR.rglob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"recordings":[
        {
            "name":    f.name,
            "path":    str(f.relative_to(RECORDINGS_DIR)),
            "size_mb": round(f.stat().st_size/1e6, 1),
            "url":     f"/recordings/{f.relative_to(RECORDINGS_DIR).as_posix()}",
            "created": time.strftime("%d %b %Y %H:%M", time.localtime(f.stat().st_mtime)),
        }
        for f in files[:100]
    ]}


@router.delete("/{filepath:path}")
async def delete_recording(filepath: str):
    p = RECORDINGS_DIR / filepath
    if p.exists(): p.unlink()
    return {"ok": True}


# ─── Replay to live stream ─────────────────────────────────────────────────
from pydantic import BaseModel as _BaseModel

class ReplayStreamReq(_BaseModel):
    file_url:  str            # /recordings/YYYY-MM-DD/match_HH-MM-SS.mp4
    rtmp_url:  str            # rtmp://a.rtmp.youtube.com/live2/KEY
    speed:     float = 0.5   # 0.25 = 4× slo-mo, 0.5 = 2× slo-mo, 1 = normal
    start_sec: float = 0.0   # start position in seconds
    duration:  float = 10.0  # clip duration in seconds


@router.post("/replay/stream")
async def replay_to_stream(req: ReplayStreamReq):
    """Send a slow-motion replay clip to RTMP live stream via FFmpeg."""
    rel = req.file_url.lstrip("/")
    if rel.startswith("recordings/"):
        rel = rel[len("recordings/"):]
    fpath = RECORDINGS_DIR / rel
    if not fpath.exists():
        raise HTTPException(404, f"Recording not found: {rel}")

    speed = max(0.1, min(2.0, req.speed))
    vf = f"setpts={1.0/speed:.4f}*PTS"
    # atempo works in 0.5–2.0 range; chain for extremes
    af = f"atempo={speed:.4f}" if speed >= 0.5 else f"atempo=0.5,atempo={speed*2:.4f}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(req.start_sec),
        "-t",  str(req.duration),
        "-i",  str(fpath),
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
        "-g", "60", "-keyint_min", "30", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "flv", req.rtmp_url
    ]
    logger.info(f"Replay stream → {req.rtmp_url} speed={speed}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return {"status": "streaming", "pid": proc.pid, "speed": speed, "duration": req.duration}
    except Exception as e:
        raise HTTPException(500, str(e))
