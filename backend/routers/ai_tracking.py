"""
SportsCaster Pro - AI Tracking Router (v5)
Renamed: Player Detection + Ball Detection + PTZ camera movement.
Supports: player photo upload, ball type selection, model upload/train/activate.
Works on Raspberry Pi (no GPU) and Windows.
"""
import asyncio, cv2, logging, os, time, threading, numpy as np
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, BackgroundTasks
from services.state import app_state

router = APIRouter()
logger = logging.getLogger("sportscaster.ai")

MODELS_DIR    = Path("../models")
TRAINING_DIR  = Path("../training_data")
BALL_DIR      = Path("../training_data/ball")
PLAYER_DIR    = Path("../training_data/player")

# Active tracking state
_stop_event    = threading.Event()
_track_thread: Optional[threading.Thread] = None
_hog           = None
_active_model  = None    # loaded cv2 model
_active_model_name = ""
_ball_type     = "cricket"  # cricket | football | hockey | custom
_track_target  = "both"     # player | ball | both

# PTZ / pan state
_ptz_state = {"x": 0.5, "y": 0.5, "zoom": 1.0}


def _get_hog():
    global _hog
    if _hog is None:
        _hog = cv2.HOGDescriptor()
        _hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return _hog


def _detect_players(frame):
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (640, 360))
    sx, sy = w/640, h/360
    rects, weights = _get_hog().detectMultiScale(small, winStride=(8,8), padding=(4,4), scale=1.05)
    dets = []
    for i, (x,y,bw,bh) in enumerate(rects):
        conf = float(weights[i]) if len(weights) > i else 0.5
        dets.append({"type":"person","x":int(x*sx),"y":int(y*sy),
                     "w":int(bw*sx),"h":int(bh*sy),"confidence":round(conf,3)})
    return dets


def _detect_ball(frame):
    """Ball detection via HoughCircles — works for any round ball."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray,(11,11),0)
    # Adjust params by ball type
    min_r = {"cricket":8,"football":15,"hockey":5,"custom":5}.get(_ball_type, 8)
    max_r = {"cricket":25,"football":45,"hockey":20,"custom":60}.get(_ball_type, 30)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, 1.2, 50,
                                param1=100, param2=30, minRadius=min_r, maxRadius=max_r)
    if circles is not None:
        x,y,r = circles[0][0]
        return {"type":"ball","ball_type":_ball_type,"x":int(x),"y":int(y),"r":int(r),"confidence":0.75}
    return None


def _update_ptz(dets, w, h):
    """Compute pan/tilt to keep tracked objects centred."""
    if not dets: return
    ball = next((d for d in dets if d["type"]=="ball"), None)
    if ball:
        cx = (ball["x"]+ball.get("r",20))/w
        cy = (ball["y"]+ball.get("r",20))/h
    else:
        xs = [d["x"]+d["w"]/2 for d in dets if d["type"]=="person"]
        ys = [d["y"]+d["h"]/2 for d in dets if d["type"]=="person"]
        cx = float(np.mean(xs))/w if xs else 0.5
        cy = float(np.mean(ys))/h if ys else 0.5
    a = 0.1
    _ptz_state["x"] = round(_ptz_state["x"]*(1-a) + cx*a, 4)
    _ptz_state["y"] = round(_ptz_state["y"]*(1-a) + cy*a, 4)
    # Update shared state
    app_state["camera_pan"]["x"] = _ptz_state["x"]
    app_state["camera_pan"]["y"] = _ptz_state["y"]


def _tracking_loop(manager, loop):
    src = app_state.get("camera_source","0")
    if src.startswith("http") or src.startswith("rtsp"):
        cap = cv2.VideoCapture(src)
    else:
        cap = cv2.VideoCapture(int(src))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,360)
    cap.set(cv2.CAP_PROP_FPS,15)
    frame_n = 0
    logger.info(f"AI tracking started — target={_track_target} ball={_ball_type}")

    while not _stop_event.is_set():
        ret, frame = cap.read()
        if not ret: time.sleep(0.1); continue
        frame_n += 1
        if frame_n % 3 != 0: continue
        h, w = frame.shape[:2]
        dets = []

        if _track_target in ("player","both"):
            dets.extend(_detect_players(frame))
        if _track_target in ("ball","both"):
            ball = _detect_ball(frame)
            if ball: dets.append(ball)

        app_state["ai_detections"] = dets
        _update_ptz(dets, w, h)

        # Auto-capture every 150 frames
        if frame_n % 150 == 0 and dets:
            TRAINING_DIR.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(TRAINING_DIR/f"auto_{int(time.time()*1000)}.jpg"), frame)

        if manager and dets:
            asyncio.run_coroutine_threadsafe(
                manager.send_event("AI_UPDATE",{
                    "detections":dets,
                    "pan":dict(_ptz_state),
                    "target":_track_target,
                    "ball_type":_ball_type
                }), loop
            )
    cap.release()
    logger.info("AI tracking stopped")


# ── Detection control ─────────────────────────────────────────────────────

@router.post("/start")
async def start_ai(request: Request):
    global _track_thread
    if app_state["ai_enabled"]: return {"status":"already_running"}
    _stop_event.clear()
    app_state["ai_enabled"] = True
    loop = asyncio.get_event_loop()
    _track_thread = threading.Thread(target=_tracking_loop,
                                     args=(request.app.state.manager, loop), daemon=True)
    _track_thread.start()
    return {"status":"started","target":_track_target,"ball_type":_ball_type}


@router.post("/stop")
async def stop_ai():
    _stop_event.set()
    app_state["ai_enabled"] = False
    app_state["ai_detections"] = []
    return {"status":"stopped"}


@router.get("/status")
async def ai_status():
    return {"enabled":app_state["ai_enabled"],"detections":app_state["ai_detections"][:10],
            "pan":_ptz_state,"target":_track_target,"ball_type":_ball_type,
            "active_model":_active_model_name}


# ── Player detection ──────────────────────────────────────────────────────

@router.post("/player/upload")
async def upload_player_photo(file: UploadFile = File(...)):
    """Upload a player reference photo for targeted tracking."""
    PLAYER_DIR.mkdir(parents=True, exist_ok=True)
    dest = PLAYER_DIR / f"player_{int(time.time()*1000)}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return {"status":"uploaded","file":dest.name,"size":len(content)}


@router.post("/player/start")
async def start_player_tracking(request: Request):
    global _track_target
    _track_target = "player"
    return await start_ai(request)


@router.post("/player/stop")
async def stop_player_tracking():
    global _track_target
    _track_target = "both"
    return await stop_ai()


# ── Ball detection ────────────────────────────────────────────────────────

@router.post("/ball/type")
async def set_ball_type(ball_type: str = "cricket"):
    """Set ball type: cricket | football | hockey | custom."""
    global _ball_type
    valid = ["cricket","football","hockey","custom"]
    if ball_type not in valid:
        raise HTTPException(400, f"ball_type must be one of {valid}")
    _ball_type = ball_type
    return {"ok":True,"ball_type":_ball_type}


@router.post("/ball/start")
async def start_ball_tracking(request: Request):
    global _track_target
    _track_target = "ball"
    return await start_ai(request)


@router.post("/ball/stop")
async def stop_ball_tracking():
    global _track_target
    _track_target = "both"
    return await stop_ai()


@router.post("/ball/upload")
async def upload_ball_image(file: UploadFile = File(...)):
    """Upload ball image for training."""
    BALL_DIR.mkdir(parents=True, exist_ok=True)
    dest = BALL_DIR / f"ball_{int(time.time()*1000)}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return {"status":"uploaded","file":dest.name}


# ── Snapshots & training ──────────────────────────────────────────────────

@router.post("/snapshot")
async def snapshot(event: str = "manual"):
    src = app_state.get("camera_source","0")
    cap = cv2.VideoCapture(src if (src.startswith("http") or src.startswith("rtsp")) else int(src))
    ret, frame = cap.read(); cap.release()
    if not ret: raise HTTPException(500,"Could not capture frame")
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    fname = TRAINING_DIR / f"{event}_{int(time.time()*1000)}.jpg"
    cv2.imwrite(str(fname), frame)
    count = len(list(TRAINING_DIR.rglob("*.jpg")))
    return {"ok":True,"file":fname.name,"total":count}


@router.get("/snapshots")
async def list_snapshots():
    files = sorted(TRAINING_DIR.rglob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True) if TRAINING_DIR.exists() else []
    return {"snapshots":[str(f.relative_to(TRAINING_DIR)) for f in files[:50]],"count":len(list(files))}


@router.post("/train")
async def trigger_training(background_tasks: BackgroundTasks, target: str = "ball"):
    """Train HOG+SVM model. target=ball|player."""
    background_tasks.add_task(_train, target)
    return {"status":"training_started","target":target}


def _train(target: str = "ball"):
    """HOG+SVM training — lightweight, works on Pi without GPU."""
    logger.info(f"Training pipeline: target={target}")
    # Collect images
    if target == "ball":
        pos_imgs = list(BALL_DIR.glob("*.jpg")) if BALL_DIR.exists() else []
        neg_imgs = list(PLAYER_DIR.glob("*.jpg")) if PLAYER_DIR.exists() else []
        # Also use auto-captures
        pos_imgs += [f for f in TRAINING_DIR.glob("ball_*.jpg")]
        neg_imgs += [f for f in TRAINING_DIR.glob("auto_*.jpg")]
    else:
        pos_imgs = list(PLAYER_DIR.glob("*.jpg")) if PLAYER_DIR.exists() else []
        neg_imgs = [f for f in TRAINING_DIR.glob("auto_*.jpg")]

    all_imgs = [(p,1) for p in pos_imgs] + [(n,0) for n in neg_imgs[:len(pos_imgs)*3]]
    if len(all_imgs) < 10:
        logger.warning(f"Not enough training data: {len(all_imgs)} images. Need ≥10.")
        return

    hog = cv2.HOGDescriptor()
    feats, labels = [], []
    for path, label in all_imgs:
        img = cv2.imread(str(path))
        if img is None: continue
        img = cv2.resize(img,(128,64))
        feats.append(hog.compute(img).flatten())
        labels.append(label)

    if len(set(labels)) < 2:
        logger.warning("Need both positive and negative samples.")
        return

    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER,200,1e-6))
    svm.train(np.array(feats,dtype=np.float32), cv2.ml.ROW_SAMPLE, np.array(labels,dtype=np.int32))
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = str(MODELS_DIR/f"{target}_model.xml")
    svm.save(model_path)
    logger.info(f"Model saved: {model_path}")


# ── Model management ──────────────────────────────────────────────────────

@router.post("/model/upload")
async def upload_model(file: UploadFile = File(...)):
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    return {"status":"uploaded","model":file.filename,"size":len(content)}


@router.get("/models")
async def list_models():
    if not MODELS_DIR.exists(): return {"models":[]}
    return {"models":[f.name for f in MODELS_DIR.iterdir() if f.is_file()]}


@router.post("/model/load/{name}")
async def load_model(name: str):
    global _active_model, _active_model_name
    p = MODELS_DIR / name
    if not p.exists(): raise HTTPException(404,"Model not found")
    try:
        if name.endswith(".xml"):
            _active_model = cv2.ml.SVM_load(str(p))
            _active_model_name = name
        elif name.endswith(".onnx"):
            _active_model = cv2.dnn.readNetFromONNX(str(p))
            _active_model_name = name
        else:
            raise HTTPException(400,"Unsupported format (.xml or .onnx only)")
        return {"status":"loaded","model":name}
    except Exception as e:
        raise HTTPException(500,str(e))


@router.post("/model/activate/{name}")
async def activate_model(name: str):
    """Alias for load — activate a model for live tracking."""
    return await load_model(name)


# ── PTZ camera movement ───────────────────────────────────────────────────

@router.post("/camera/move")
async def move_camera(x: float = 0.5, y: float = 0.5, zoom: float = 1.0):
    """
    Send PTZ movement command.
    x,y = normalised 0..1 (0.5 = centre)
    For ONVIF PTZ cameras: translate to pan/tilt degrees.
    For USB cameras: apply digital crop/zoom in overlay.
    """
    _ptz_state.update({"x": round(x,4), "y": round(y,4), "zoom": round(zoom,2)})
    app_state["camera_pan"]["x"] = _ptz_state["x"]
    app_state["camera_pan"]["y"] = _ptz_state["y"]
    # TODO: Add ONVIF PTZ control here for IP PTZ cameras
    return {"ok":True,"ptz":_ptz_state}


@router.get("/camera/ptz")
async def get_ptz():
    return _ptz_state
