"""
SportsCaster Pro - Streaming Router v11
Fixes:
  - Windows dshow: removed invalid -pixel_format mjpeg option
  - Windows dshow: -video_size and -framerate are now optional (not forced),
    preventing "Invalid argument" on cameras that don't support them
  - HTTP streams (mobile IP Webcam): no -rtsp_transport option
  - RTSP streams: keep -rtsp_transport tcp
  - Multi-stream support (different stream_id per camera)
  - High quality defaults: 4000k bitrate, hw encoder detection
"""
import asyncio, logging, os, re, subprocess, threading, time
from pathlib import Path
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.db import get_setting, set_setting
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.streaming")

# Active streams: stream_id → {proc, log_path, rtmp, camera, platform, started_at}
_streams: Dict[str, dict] = {}


class StreamConfig(BaseModel):
    stream_id:     str           = "main"
    platform:      str           = "youtube"
    stream_url:    Optional[str] = ""
    stream_key:    str           = ""
    resolution:    str           = "1280x720"
    bitrate:       str           = "4000k"
    fps:           int           = 30
    camera_source: Optional[str] = None


def _rtmp(cfg: StreamConfig) -> str:
    k = cfg.stream_key.strip()
    if cfg.platform == "youtube":  return f"rtmp://a.rtmp.youtube.com/live2/{k}"
    if cfg.platform == "facebook": return f"rtmps://live-api-s.facebook.com:443/rtmp/{k}"
    base = (cfg.stream_url or "").rstrip("/")
    return f"{base}/{k}" if k else base


def _get_dshow_devices() -> list:
    """List Windows DirectShow video device names via ffmpeg."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=10
        )
        return re.findall(r'"([^"]+)"\s*\(video\)', r.stderr, re.IGNORECASE)
    except Exception:
        return []


def _classify_device(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["integrated", "built-in", "builtin", "internal",
                              "facetime", "isight", "front", "laptop"]):
        return "integrated"
    return "usb"


def _resolve_camera_input(src: str, fps: int, res: str) -> list:
    """
    Build correct FFmpeg input arguments for any camera source.

    Windows dshow rules (critical):
      - DO NOT use -pixel_format (dshow ignores / rejects it)
      - DO NOT force -video_size or -framerate unless camera supports it
      - Use plain: -f dshow -i "video=Device Name"

    Linux v4l2:
      - CAN use -input_format mjpeg, -video_size, -framerate

    HTTP (IP Webcam app, MJPEG):
      - Plain: -i http://...   (NO -rtsp_transport)

    RTSP:
      - -rtsp_transport tcp -i rtsp://...
    """
    if not src or src.strip() == "":
        src = "0"

    # ── RTSP streams ──────────────────────────────────────────────────────
    if src.startswith("rtsp") or src.startswith("rtsps"):
        return ["-rtsp_transport", "tcp", "-i", src]

    # ── HTTP streams (IP Webcam, MJPEG server) ────────────────────────────
    if src.startswith("http"):
        # Plain HTTP — no transport option, just read the stream
        return ["-i", src]

    # ── Windows DirectShow ────────────────────────────────────────────────
    if os.name == "nt":
        # Resolve device name from index if numeric
        if src.isdigit():
            devices = _get_dshow_devices()
            if devices:
                idx = min(int(src), len(devices) - 1)
                device_name = devices[idx]
            else:
                device_name = src
        elif src.startswith("video="):
            device_name = src[6:]
        else:
            device_name = src  # already a device name

        # IMPORTANT: Do NOT add -pixel_format, -video_size, or -framerate
        # for dshow on Windows — they cause "Invalid argument" on most webcams.
        # Let FFmpeg and dshow negotiate the best format automatically.
        return [
            "-f", "dshow",
            "-i", f"video={device_name}",
        ]

    # ── Linux / Raspberry Pi — v4l2 ───────────────────────────────────────
    if src.isdigit():
        dev = f"/dev/video{src}"
    elif src.startswith("/dev/"):
        dev = src
    else:
        dev = f"/dev/video{src}"

    # v4l2 supports -input_format mjpeg for efficiency
    return [
        "-f", "v4l2",
        "-input_format", "mjpeg",
        "-video_size", res,
        "-framerate", str(fps),
        "-i", dev,
    ]


def _best_encoder() -> list:
    """
    Detect hardware encoder, fall back to libx264.
    Correct encoder flags per encoder type.
    """
    try:
        out = subprocess.check_output(
            ["ffmpeg", "-encoders"], stderr=subprocess.STDOUT, text=True, timeout=8
        )
        if "h264_v4l2m2m" in out:
            logger.info("HW encoder: h264_v4l2m2m (Raspberry Pi)")
            return ["-c:v", "h264_v4l2m2m"]
        if "h264_nvenc" in out:
            logger.info("HW encoder: h264_nvenc (NVIDIA)")
            return [
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-profile:v", "main",
                "-level", "4.1",
            ]
        if "h264_qsv" in out:
            logger.info("HW encoder: h264_qsv (Intel)")
            return ["-c:v", "h264_qsv", "-profile:v", "main"]
    except Exception:
        pass

    # CPU libx264 — best compatibility for all platforms
    return [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", "main",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
    ]


def _build_cmd(cfg: StreamConfig, rtmp_url: str) -> list:
    src = cfg.camera_source or app_state.get("camera_source", "0") or "0"
    fps, res = cfg.fps, cfg.resolution
    w, h = res.split("x")
    gop = fps * 2

    cam_args   = _resolve_camera_input(src, fps, res)
    audio_args = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]

    # Scale to target resolution, pad black bars if needed, force yuv420p
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"format=yuv420p"
    )

    enc = _best_encoder()
    br  = cfg.bitrate.lower().rstrip("k") + "k" if cfg.bitrate.lower().endswith("k") else cfg.bitrate
    buf = str(int(cfg.bitrate.rstrip("kKmM")) * 2) + "k"

    return (
        ["ffmpeg", "-y"]
        + cam_args
        + audio_args
        + ["-vf", vf]
        + enc
        + [
            "-b:v", br, "-maxrate", br, "-bufsize", buf,
            "-g",   str(gop), "-keyint_min", str(fps), "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-shortest", "-f", "flv", rtmp_url,
        ]
    )


def _log_stderr(proc, log_path: Path, stream_id: str):
    with open(log_path, "w", encoding="utf-8", errors="replace") as f:
        for line in iter(proc.stderr.readline, b""):
            text = line.decode(errors="replace").rstrip()
            f.write(text + "\n")
            f.flush()
            if any(k in text.lower() for k in ("error", "failed", "fps=", "bitrate=", "opening")):
                logger.info(f"[ffmpeg:{stream_id}] {text}")


@router.post("/start")
async def start_stream(cfg: StreamConfig, request: Request):
    """Start a stream. Multiple streams with different stream_id run simultaneously."""
    stream_id = cfg.stream_id.strip() or "main"

    if stream_id in _streams and _streams[stream_id]["proc"].poll() is None:
        raise HTTPException(409, f"Stream '{stream_id}' already running. Stop it first or use a different ID.")

    if not cfg.stream_key.strip() and not (cfg.stream_url or "").strip():
        raise HTTPException(400, "stream_key is required")

    rtmp_url = _rtmp(cfg)
    cmd      = _build_cmd(cfg, rtmp_url)

    logs_dir = Path("../config")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"ffmpeg_{stream_id}.log"

    logger.info(f"[{stream_id}] → {rtmp_url}")
    logger.info(f"[{stream_id}] CMD: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, bufsize=0
        )
    except FileNotFoundError:
        raise HTTPException(500, "FFmpeg not found. Install FFmpeg and add to PATH.")
    except Exception as e:
        raise HTTPException(500, str(e))

    threading.Thread(
        target=_log_stderr, args=(proc, log_path, stream_id), daemon=True
    ).start()

    await asyncio.sleep(2)
    if proc.poll() is not None:
        try:    last = log_path.read_text(errors="replace")[-2000:]
        except: last = "(no log)"
        raise HTTPException(500, f"FFmpeg exited immediately for stream '{stream_id}'.\n\nLog:\n{last}")

    _streams[stream_id] = {
        "proc":       proc,
        "log_path":   log_path,
        "rtmp":       rtmp_url,
        "camera":     cfg.camera_source or app_state.get("camera_source", ""),
        "platform":   cfg.platform,
        "started_at": time.strftime("%H:%M:%S"),
    }

    app_state["stream_status"] = "live"
    app_state["stream_pid"]    = proc.pid
    set_setting("stream_key", cfg.stream_key)
    if cfg.stream_url:
        set_setting("stream_url", cfg.stream_url)

    try:
        await request.app.state.manager.send_event("STREAM_STATUS", {
            "status": "live", "stream_id": stream_id,
            "pid": proc.pid, "rtmp": rtmp_url,
            "active_streams": list(_streams.keys()),
        })
    except Exception:
        pass

    return {
        "status": "live", "stream_id": stream_id,
        "pid": proc.pid, "rtmp": rtmp_url,
        "active_streams": list(_streams.keys()),
    }


@router.post("/stop")
async def stop_stream(stream_id: str = "main", request: Request = None):
    """Stop a specific stream by stream_id. Use stream_id=all to stop everything."""
    if stream_id == "all":
        stopped = []
        for sid, info in list(_streams.items()):
            if info["proc"].poll() is None:
                info["proc"].terminate()
                try:    info["proc"].wait(timeout=5)
                except: info["proc"].kill()
            del _streams[sid]
            stopped.append(sid)
        app_state["stream_status"] = "idle"
        app_state["stream_pid"]    = None
        try:
            if request:
                await request.app.state.manager.send_event("STREAM_STATUS",
                    {"status": "idle", "stopped": stopped})
        except Exception:
            pass
        return {"status": "stopped", "stopped": stopped}

    if stream_id not in _streams:
        return {"status": "not_running", "stream_id": stream_id}

    proc = _streams[stream_id]["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:    proc.wait(timeout=6)
        except subprocess.TimeoutExpired: proc.kill()

    del _streams[stream_id]

    if not _streams:
        app_state["stream_status"] = "idle"
        app_state["stream_pid"]    = None

    try:
        if request:
            await request.app.state.manager.send_event("STREAM_STATUS", {
                "status": "idle" if not _streams else "live",
                "stream_id": stream_id,
                "active_streams": list(_streams.keys()),
            })
    except Exception:
        pass

    return {
        "status": "stopped", "stream_id": stream_id,
        "active_streams": list(_streams.keys()),
    }


@router.get("/status")
async def stream_status():
    active, dead = {}, []
    for sid, info in _streams.items():
        if info["proc"].poll() is None:
            active[sid] = {
                "running":    True,
                "pid":        info["proc"].pid,
                "rtmp":       info["rtmp"],
                "camera":     info["camera"],
                "platform":   info["platform"],
                "started_at": info["started_at"],
            }
        else:
            dead.append(sid)
    for sid in dead:
        del _streams[sid]
    running = len(active) > 0
    app_state["stream_status"] = "live" if running else "idle"
    return {
        "running":        running,
        "status":         "live" if running else "idle",
        "active_streams": active,
        "stream_count":   len(active),
    }


@router.get("/log")
async def get_log(stream_id: str = "main"):
    log_path = Path("../config") / f"ffmpeg_{stream_id}.log"
    if log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()
        return {"lines": lines[-100:], "stream_id": stream_id}
    return {"lines": ["No log yet."], "stream_id": stream_id}


@router.get("/list-devices")
async def list_devices():
    """List all cameras with type: integrated, usb, all."""
    result = {
        "platform":   "windows" if os.name == "nt" else "linux",
        "integrated": [], "usb": [], "all": []
    }
    if os.name == "nt":
        devices = _get_dshow_devices()
        for i, name in enumerate(devices):
            t   = _classify_device(name)
            cam = {"index": i, "name": name, "url": str(i), "type": t}
            result[t].append(cam)
            result["all"].append(cam)
        if not devices:
            cam = {"index": 0, "name": "Default Camera", "url": "0", "type": "usb"}
            result["usb"].append(cam); result["all"].append(cam)
    else:
        import glob
        for dev in sorted(glob.glob("/dev/video*")):
            idx  = dev.replace("/dev/video", "")
            name = f"Camera {idx}"
            t    = "integrated" if idx == "0" else "usb"
            try:
                r = subprocess.run(["v4l2-ctl", "--device", dev, "--info"],
                                   capture_output=True, text=True, timeout=3)
                for line in r.stdout.splitlines():
                    if "Card type" in line:
                        name = line.split(":")[-1].strip(); break
                t = _classify_device(name)
            except Exception:
                pass
            cam = {"index": idx, "name": name, "url": idx, "type": t, "device": dev}
            result[t if t in result else "usb"].append(cam)
            result["all"].append(cam)
        if not result["all"]:
            cam = {"index": "0", "name": "USB Camera 0", "url": "0", "type": "usb"}
            result["usb"].append(cam); result["all"].append(cam)
    return result


@router.get("/test-camera")
async def test_camera(source: str = "0"):
    """Test if a camera source opens successfully."""
    args = _resolve_camera_input(source, 15, "640x480")
    cmd  = ["ffmpeg"] + args + ["-frames:v", "3", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        ok = r.returncode == 0
        return {"ok": ok, "source": source, "output": (r.stdout + r.stderr)[-800:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "source": source, "output": "Timeout — camera not responding"}
    except Exception as e:
        return {"ok": False, "source": source, "output": str(e)}
