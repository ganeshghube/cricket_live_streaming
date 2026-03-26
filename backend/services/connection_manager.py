import json, logging
from typing import List
from fastapi import WebSocket

logger = logging.getLogger("sportscaster.ws")

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        text = json.dumps(data)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_event(self, event_type: str, payload: dict):
        await self.broadcast({"type": event_type, "payload": payload})
