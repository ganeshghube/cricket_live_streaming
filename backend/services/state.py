"""
Shared in-memory state — single source of truth for all modules.
All routers read/write here; WebSocket broadcasts changes to frontend.
"""

app_state: dict = {
    "active_sport":      "cricket",
    "match_id":          None,
    "score":             {},
    "camera_source":     "",          # Active camera URL or index string
    "stream_status":     "idle",      # idle | live | error
    "stream_pid":        None,
    "recording_status":  "idle",      # idle | recording
    "recording_pid":     None,
    "recording_file":    None,
    "ai_enabled":        False,
    "ai_detections":     [],
    "camera_pan":        {"x": 0.5, "y": 0.5},
    "last_event":        None,
    "popup":             None,
}
