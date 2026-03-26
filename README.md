# SportsCaster Pro V1

**Complete rebuild**: vertical sidebar + sub-tabs, camera source management, overlay sync, streaming/recording fix, replay fix, AI tracking.

---

## What's Fixed in V1

| Issue | Fix |
|---|---|
| Top tabs → left sidebar | Vertical sidebar with expand/collapse |
| Dropdowns → sub-tabs | Persistent sub-tabs per section |
| Preview not working | Direct MJPEG `<img>` for IP/mobile cameras |
| Overlay not syncing | Single WS source, INIT event on connect |
| Recording buttons broken | Proper Popen management + state broadcast |
| Streaming buttons broken | Fixed FFmpeg cmd + status tracking |
| Replay not loading | `/recordings/` served as static, list API fixed |
| IP camera not saveable | Full camera_sources table + CRUD UI |

---

## Folder Structure

```
sportscaster2/
├── backend/
│   ├── main.py              # App + WebSocket + static mounts
│   ├── routers/
│   │   ├── auth.py          # Login/logout
│   │   ├── cameras.py       # Camera source CRUD ← NEW
│   │   ├── scoring.py       # All sports scoring engine
│   │   ├── streaming.py     # FFmpeg stream start/stop
│   │   ├── recording.py     # Local recording start/stop
│   │   ├── review.py        # VAR/wicket review clips
│   │   ├── ai_tracking.py   # AI detection, training, models
│   │   └── settings.py      # Settings CRUD
│   └── services/
│       ├── db.py            # SQLite + camera_sources table
│       ├── state.py         # Shared app state (single source of truth)
│       └── connection_manager.py
├── frontend/
│   ├── index.html           # Vertical sidebar + sub-tabs
│   └── app.js               # All frontend logic
├── overlay/
│   └── index.html           # 1920×1080 overlay, WS synced
├── scripts/
│   ├── setup_windows.sh     # Windows Git Bash setup
│   ├── install_pi.sh        # Full Pi installation
│   ├── setup_hotspot.sh     # WiFi AP setup
│   └── ffmpeg_pipeline.sh   # Manual FFmpeg pipeline
├── recordings/              # Auto-managed (max 5)
├── reviews/                 # VAR clips
├── models/                  # AI models
├── training_data/           # Snapshots
├── config/
│   └── sports_rules.json
├── requirements.txt
├── run.py                   # Dev launcher
└── start_windows.bat        # Windows double-click
```

---

## Quick Start (Windows)

```bash
# 1. Setup (one time, in Git Bash from sportscaster2 folder)
bash scripts/setup_windows.sh

# 2. Start
venv/Scripts/python run.py

# 3. Open
# http://localhost:3000  →  admin / admin
```

Or double-click **start_windows.bat**.

---

## Quick Start (Raspberry Pi)

```bash
sudo bash scripts/install_pi.sh
# Reboots automatically
# Connect phone to WiFi: SportsCaster / broadcast1
# Open: http://192.168.4.1:3000
```

---

## UI Navigation

```
LEFT SIDEBAR
│
├── 🏅 Scoring
│   ├── Cricket       ← Full batting/bowling/extras UI
│   ├── Football      ← Goals, cards, half-time
│   ├── Hockey        ← Goals, penalty corners, quarters
│   ├── Volleyball    ← Points, timeouts, sets
│   └── Custom        ← Generic +1 scorer
│
├── 📷 Camera
│   ├── USB Camera    ← Index select + auto-detect
│   ├── IP Camera     ← URL input, test, save
│   ├── Mobile Camera ← IP Webcam instructions + save
│   └── Saved Sources ← All cameras + Set Active + delete
│
├── 📡 Streaming
│   ├── RTMP Settings ← Platform, key, bitrate config
│   ├── Live Stream   ← Start/Stop stream + overlay preview
│   └── Recording     ← Start/Stop local recording
│
├── ⏮ Replay
│   ├── Recordings    ← Load from /recordings/, HTML5 player
│   └── Reviews       ← Save/play VAR clips, OUT/NOT OUT
│
├── 🤖 AI Tracking
│   ├── Player Detection ← HOG+SVM, live detections, pan
│   ├── Ball Tracking    ← HoughCircles, position display
│   ├── Training         ← Snapshot count, trigger training
│   └── Model Upload     ← Upload .xml/.onnx, load model
│
└── ⚙️ Settings
    ├── General       ← Stream key, URL
    └── Hotspot       ← SSID/pass for Pi
```

---

## Camera Setup

### USB Camera
1. Camera → USB Camera
2. Click **🔍 Auto Detect** to find cameras
3. Select index → **✓ Set Active**

### IP Camera (e.g. security camera, RTSP-to-HTTP)
1. Camera → IP Camera
2. Enter label + URL (e.g. `http://192.168.1.10:8080/video`)
3. **🔗 Test** → **💾 Save** (auto-sets as active)
4. Live MJPEG preview appears immediately

### Mobile Camera (Android IP Webcam)
1. Install **IP Webcam** from Play Store
2. Tap **Start Server** — note IP shown
3. Camera → Mobile Camera
4. Enter `http://[phone-ip]:8080/video`
5. **💾 Save & Set Active**

> All saved sources persist in SQLite. The **active** source is shared by streaming, recording, AI tracking, and review — no duplication.

---

## Streaming

1. **Streaming → RTMP Settings**: choose platform, enter stream key, save
2. **Streaming → Live Stream**: tap **▶ Go Live**
3. Overlay updates automatically via WebSocket
4. **■ Stop Stream** when done

### YouTube
- YouTube Studio → Go Live → Stream → copy **Stream Key**

### Facebook  
- Facebook → Live Video → Use Stream Key → copy key

---

## Recording & Replay

- **Streaming → Recording → ⏺ Start Recording**
- Saved to `/recordings/` — oldest auto-deleted when >5 files
- **Replay → Recordings** — click any file to play
- Speed controls: 0.1×, 0.25×, 0.5×, 1×
- Frame-by-frame: ◀ Frame / Frame ▶

---

## VAR / Review

- **Replay → Reviews → Save Last 12s** — captures clip from active camera
- Play back with slow-motion controls
- Tap **OUT ✓** or **NOT OUT ✗** — decision shown on screen and broadcast to overlay

---

## AI Tracking

- **AI Tracking → Player Detection → ▶ Start AI**
- Person detection via HOG descriptor (no GPU, runs on Pi 4)
- Ball detection via HoughCircles
- Camera pan coordinates updated live
- Snapshots auto-saved every 150 frames to `/training_data/`

### Training workflow
1. Collect snapshots (manual + auto-capture)
2. Rename ball images: `ball_001.jpg`, `ball_002.jpg`, ...
3. **AI Tracking → Training → 🧠 Start Training**
4. Model saved to `/models/custom_model.xml`
5. **AI Tracking → Model Upload** → click model → **Load**

---

## Overlay

The overlay (`/overlay/index.html`) connects to the same WebSocket and updates in real time. It is:
- Served at `http://localhost:8000/overlay/index.html`
- Embedded as iframe preview in Camera and Streaming tabs
- Composited into stream by FFmpeg (via `overlay_static.png` or live capture)

---

## Troubleshooting

**Backend won't start (Windows)**
```bash
venv/Scripts/python -m uvicorn main:app --reload --port 8000
# Read the error message — usually a missing import
```

**Camera preview blank**
- USB cameras can't be previewed directly in browser — use IP Webcam app for mobile preview
- IP camera: check URL is `http://` not `rtsp://` — browsers can't play RTSP

**FFmpeg not found**
- Download: https://ffmpeg.org/download.html
- Windows: extract zip, add `bin/` folder to System PATH
- Restart Git Bash after adding to PATH

**Recordings not showing in Replay**
- Check `/recordings/` folder exists and has `.mp4` files
- Click **🔄 Refresh** button in Replay tab

**Pi hotspot not appearing**
```bash
sudo systemctl status hostapd
sudo journalctl -u hostapd -n 30
```

---

## Performance Notes (Raspberry Pi 4)

| Component | CPU Usage |
|---|---|
| FastAPI + WebSocket | ~3% |
| FFmpeg stream (hw enc) | ~25% |
| AI HOG detection (15fps) | ~35% |
| Total with streaming + AI | ~60-70% |

Tips for reducing CPU:
- Disable AI when streaming (`Stop AI` before `Go Live`)
- Reduce AI frame processing: change `% 3` to `% 5` in `ai_tracking.py`
- Use 720p instead of 1080p for recording
