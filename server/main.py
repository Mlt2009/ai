"""Companion server — FastAPI app with a real-time WebSocket voice channel.

Run:  python -m server.main   (or ./run.sh)
Then open the printed URL on your phone or computer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AI Companion")
atlas = Orchestrator()


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/team")
async def team():
    return {"orchestrator": "Atlas", "agents": atlas.team_roster()}


@app.get("/api/stats")
async def live_stats():
    """Lightweight live stats for the dashboard tiles."""
    vm = psutil.virtual_memory()
    return {
        "cpu": psutil.cpu_percent(interval=0.1),
        "mem": vm.percent,
        "gemini": bool(config.GEMINI_API_KEY),
        "home_assistant": bool(config.HA_TOKEN),
        "octoprint": bool(config.OCTOPRINT_API_KEY),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(uuid.uuid4())
    log.info("client connected: %s", session_id)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"type": "user_text", "text": raw}

            if msg.get("type") == "reset":
                atlas.reset(session_id)
                await ws.send_json({"type": "reply", "text": "Fresh start — what's next?"})
                continue

            text = (msg.get("text") or "").strip()
            if not text:
                continue
            async for event in atlas.respond(session_id, text):
                await ws.send_json(event)
            await ws.send_json({"type": "turn_end"})
    except WebSocketDisconnect:
        atlas.reset(session_id)
        log.info("client disconnected: %s", session_id)


app.mount("/", StaticFiles(directory=WEB_DIR), name="static")


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def print_banner() -> None:
    url = f"http://{lan_ip()}:{config.PORT}"
    print("\n" + "=" * 52)
    print("  AI COMPANION — Atlas is online")
    print(f"  On this computer : http://localhost:{config.PORT}")
    print(f"  On your phone    : {url}")
    print("  (same Wi-Fi network — scan the QR code below,")
    print("   then 'Add to Home Screen' to install the app)")
    print("=" * 52)
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        pass


if __name__ == "__main__":
    print_banner()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
