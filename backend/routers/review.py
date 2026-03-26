"""SportsCaster Pro v2 - Review/VAR Router"""

import logging, os, subprocess, time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
logger = logging.getLogger("sportscaster.review")
REVIEWS_DIR = Path("../reviews")


@router.post("/save")
async def save_review(event_type: str = "wicket", duration: int = 12):
    from services.state import app_state
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    output = str(REVIEWS_DIR / f"review_{event_type}_{ts}.mp4")
    src = app_state.get("camera_source", "0")

    if src.startswith("http"):
        cmd = ["ffmpeg", "-i", src, "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-y", output]
    elif os.name == "nt":
        cmd = ["ffmpeg", "-f", "dshow", "-i", f"video={src}", "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-y", output]
    else:
        cmd = ["ffmpeg", "-f", "v4l2", "-i", f"/dev/video{src}", "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast", "-y", output]

    try:
        subprocess.run(cmd, timeout=duration + 10)
    except Exception as e:
        logger.error(f"Review clip failed: {e}")
        return {"status": "error", "error": str(e)}

    return {"status": "saved", "file": Path(output).name}


@router.get("/list")
async def list_reviews():
    if not REVIEWS_DIR.exists():
        return {"reviews": []}
    files = sorted(REVIEWS_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"reviews": [
        {"name": f.name, "url": f"/reviews/{f.name}",
         "size_mb": round(f.stat().st_size / 1e6, 2),
         "created": time.strftime("%d %b %Y %H:%M", time.localtime(f.stat().st_mtime)),
         "event": f.stem.split("_")[1] if "_" in f.stem else "unknown"}
        for f in files[:20]
    ]}


@router.delete("/{filename}")
async def delete_review(filename: str):
    p = REVIEWS_DIR / filename
    if p.exists(): p.unlink()
    return {"ok": True}
