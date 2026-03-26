"""
SportsCaster Pro - Streaming Router
FIX: dshow camera name detection, silent audio always present,
     correct h264 profile, GOP for YouTube, debug log endpoint.
"""
import asyncio, logging, os, re, subprocess, threading
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.db import get_setting, set_setting
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.streaming")

_stream_proc: Optional[subprocess.Popen] = None
_ffmpeg_log:  Optional[Path]             = None
_log_thread:  Optional[threading.Thread] = None


class StreamConfig(BaseModel):
    platform:      str           = "youtube"
    stream_url:    Optional[str] = ""
    stream_key:    str           = ""
    resolution:    str           = "1280x720"
    bitrate:       str           = "2500k"
    fps:           int           = 30
    camera_source: Optional[str] = None


def _rtmp(cfg: StreamConfig) -> str:
    k = cfg.stream_key.strip()
    if cfg.platform == "youtube":  return f"rtmp://a.rtmp.youtube.com/live2/{k}"
    if cfg.platform == "facebook": return f"rtmps://live-api-s.facebook.com:443/rtmp/{k}"
    base = (cfg.stream_url or "").rstrip("/")
    return f"{base}/{k}" if k else base


def _get_dshow_devices() -> list[str]:
    """List Windows DirectShow video device names."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=8
        )
        return re.findall(r'"([^"]+)"\s*\(video\)', r.stderr, re.IGNORECASE)
    except Exception:
        return []


def _resolve_camera_input(src: str, fps: int, res: str) -> list[str]:
    """
    FIX: Build correct camera input args for Windows/Linux/IP.
    Windows dshow requires the quoted device NAME not index.
    """
    if not src or src.strip() == "":
        src = "0"

    # IP / RTSP / HTTP stream
    if src.startswith("http") or src.startswith("rtsp"):
        return ["-rtsp_transport", "tcp", "-i", src]

    # Windows DirectShow
    if os.name == "nt":
        # If src is a digit, resolve to device name
        if src.isdigit():
            devices = _get_dshow_devices()
            if devices:
                idx = min(int(src), len(devices)-1)
                device_name = devices[idx]
            else:
                device_name = f"video={src}"
        elif src.startswith("video="):
            device_name = src          # already formatted
        else:
            device_name = src          # bare name from UI
        return [
            "-f", "dshow",
            "-video_size", res,
            "-framerate", str(fps),
            "-i", f"video={device_name}",
        ]

    # Linux / Pi v4l2
    dev = f"/dev/video{src}" if src.isdigit() else src
    return [
        "-f", "v4l2",
        "-input_format", "mjpeg",
        "-video_size", res,
        "-framerate", str(fps),
        "-i", dev,
    ]


def _best_encoder() -> list[str]:
    try:
        out = subprocess.check_output(["ffmpeg","-encoders"],
            stderr=subprocess.STDOUT, text=True, timeout=6)
        if "h264_v4l2m2m" in out:
            logger.info("HW encoder: h264_v4l2m2m")
            return ["-c:v","h264_v4l2m2m","-b:v","2500k"]
    except Exception:
        pass
    return ["-c:v","libx264","-preset","veryfast","-tune","zerolatency",
            "-profile:v","main","-level","4.0"]


def _double_br(br: str) -> str:
    try:
        v=int(br.rstrip("kKmM")); u=br[-1].lower(); return f"{v*2}{u}"
    except Exception:
        return "5000k"


def _build_cmd(cfg: StreamConfig, rtmp_url: str) -> list[str]:
    src = cfg.camera_source or app_state.get("camera_source","0")
    fps, res = cfg.fps, cfg.resolution
    w, h = res.split("x")
    gop = fps * 2

    cam_args = _resolve_camera_input(src, fps, res)
    # Always add silent audio so YouTube never rejects for missing audio track
    audio_args = ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    enc = _best_encoder()

    return (
        ["ffmpeg","-y"]
        + cam_args
        + audio_args
        + ["-vf",vf]
        + enc
        + ["-b:v",cfg.bitrate,"-maxrate",cfg.bitrate,"-bufsize",_double_br(cfg.bitrate),
           "-g",str(gop),"-keyint_min",str(fps),"-sc_threshold","0",
           "-c:a","aac","-b:a","128k","-ar","44100","-ac","2",
           "-shortest","-f","flv",rtmp_url]
    )


def _log_stderr(proc, log_path: Path):
    with open(log_path,"w",encoding="utf-8",errors="replace") as f:
        for line in iter(proc.stderr.readline, b""):
            text = line.decode(errors="replace").rstrip()
            f.write(text+"\n"); f.flush()
            if any(k in text.lower() for k in ("error","failed","fps=","bitrate=","opening")):
                logger.info(f"[ffmpeg] {text}")


@router.post("/start")
async def start_stream(cfg: StreamConfig, request: Request):
    global _stream_proc, _ffmpeg_log, _log_thread
    if _stream_proc and _stream_proc.poll() is None:
        raise HTTPException(409, "Already streaming")
    if not cfg.stream_key.strip() and not (cfg.stream_url or "").strip():
        raise HTTPException(400, "stream_key required")

    rtmp_url = _rtmp(cfg)
    cmd = _build_cmd(cfg, rtmp_url)
    logs_dir = Path("../config"); logs_dir.mkdir(parents=True,exist_ok=True)
    _ffmpeg_log = logs_dir / "ffmpeg_stream.log"

    logger.info(f"Stream → {rtmp_url}")
    logger.info(f"CMD: {' '.join(cmd)}")

    try:
        _stream_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, bufsize=0)
    except FileNotFoundError:
        raise HTTPException(500,"FFmpeg not found. Install FFmpeg and add to PATH.")
    except Exception as e:
        raise HTTPException(500, str(e))

    _log_thread = threading.Thread(target=_log_stderr,
                                   args=(_stream_proc,_ffmpeg_log), daemon=True)
    _log_thread.start()

    await asyncio.sleep(2)
    if _stream_proc.poll() is not None:
        try: last = _ffmpeg_log.read_text(errors="replace")[-1200:]
        except Exception: last = "(no log)"
        raise HTTPException(500, f"FFmpeg exited immediately.\n\nSee /api/stream/log\n\nLast output:\n{last}")

    pid = _stream_proc.pid
    app_state["stream_status"] = "live"
    app_state["stream_pid"] = pid
    set_setting("stream_key", cfg.stream_key)
    if cfg.stream_url: set_setting("stream_url", cfg.stream_url)
    try:
        await request.app.state.manager.send_event("STREAM_STATUS",{"status":"live","pid":pid})
    except Exception: pass
    return {"status":"live","pid":pid,"rtmp":rtmp_url}


@router.post("/stop")
async def stop_stream(request: Request):
    global _stream_proc
    if _stream_proc and _stream_proc.poll() is None:
        _stream_proc.terminate()
        try: _stream_proc.wait(timeout=6)
        except subprocess.TimeoutExpired: _stream_proc.kill()
    _stream_proc = None
    app_state["stream_status"] = "idle"; app_state["stream_pid"] = None
    try:
        await request.app.state.manager.send_event("STREAM_STATUS",{"status":"idle"})
    except Exception: pass
    return {"status":"stopped"}


@router.get("/status")
async def stream_status():
    running = _stream_proc is not None and _stream_proc.poll() is None
    if not running: app_state["stream_status"]="idle"; app_state["stream_pid"]=None
    return {"status":app_state["stream_status"],"running":running,
            "pid":_stream_proc.pid if running else None}


@router.get("/log")
async def get_log():
    """Debug: last 100 lines of FFmpeg stderr."""
    if _ffmpeg_log and _ffmpeg_log.exists():
        lines = _ffmpeg_log.read_text(errors="replace").splitlines()
        return {"lines":lines[-100:],"path":str(_ffmpeg_log)}
    return {"lines":["No log yet."]}


@router.get("/list-devices")
async def list_devices():
    """Windows: list DirectShow devices. Linux: list /dev/video*."""
    if os.name == "nt":
        devices = _get_dshow_devices()
        return {"platform":"windows","devices":devices,
                "usage":'Use device name exactly, e.g. "USB Video Device"'}
    else:
        import glob
        devs = sorted(glob.glob("/dev/video*"))
        return {"platform":"linux","devices":devs,
                "usage":"Use index number e.g. 0 for /dev/video0"}


@router.get("/test-camera")
async def test_camera(source: str = "0"):
    """Validate camera before streaming."""
    args = _resolve_camera_input(source, 15, "640x360")
    cmd = ["ffmpeg"] + args + ["-frames:v","3","-f","null","-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"ok": r.returncode==0, "output": (r.stdout+r.stderr)[-600:]}
    except subprocess.TimeoutExpired:
        return {"ok":False,"output":"Timed out — camera not found"}
    except Exception as e:
        return {"ok":False,"output":str(e)}
