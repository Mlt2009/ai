"""Companion server — FastAPI app with a real-time WebSocket voice channel.

Run:  python -m server.main   (or ./run.sh)
Then open the printed URL on your phone or computer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import uuid
from pathlib import Path

import httpx
import psutil
import uvicorn
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
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


def _mask(secret: str) -> str:
    return f"••••{secret[-4:]}" if secret else ""


async def _service_checks() -> dict:
    """Live reachability tests for every integration (best-effort, fast)."""

    async def check_gemini():
        if not config.GEMINI_API_KEY:
            return {"on": False, "detail": "no API key"}
        try:
            from google import genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            await asyncio.wait_for(
                client.aio.models.get(model=config.GEMINI_MODEL), timeout=6)
            return {"on": True, "detail": f"connected · {config.GEMINI_MODEL}"}
        except Exception as exc:
            return {"on": False, "detail": f"key set but check failed: {type(exc).__name__}"}

    async def check_ha():
        if not config.HA_TOKEN:
            return {"on": False, "detail": "no token"}
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{config.HA_URL}/api/",
                                headers={"Authorization": f"Bearer {config.HA_TOKEN}"})
            return ({"on": True, "detail": "connected"} if r.status_code == 200
                    else {"on": False, "detail": f"HTTP {r.status_code}"})
        except Exception as exc:
            return {"on": False, "detail": f"unreachable: {type(exc).__name__}"}

    async def check_octoprint():
        if not config.OCTOPRINT_API_KEY:
            return {"on": False, "detail": "no API key"}
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{config.OCTOPRINT_URL}/api/version",
                                headers={"X-Api-Key": config.OCTOPRINT_API_KEY})
            return ({"on": True, "detail": f"connected · {r.json().get('text', 'OctoPrint')}"}
                    if r.status_code == 200
                    else {"on": False, "detail": f"HTTP {r.status_code}"})
        except Exception as exc:
            return {"on": False, "detail": f"unreachable: {type(exc).__name__}"}

    async def check_cups():
        if not shutil.which("lp"):
            return {"on": False, "detail": "CUPS not installed on server"}
        return {"on": True, "detail": config.CUPS_PRINTER or "system default printer"}

    gemini, ha, octo, cups = await asyncio.gather(
        check_gemini(), check_ha(), check_octoprint(), check_cups())
    return {
        "gemini": gemini,
        "home_assistant": ha,
        "octoprint": octo,
        "cups": cups,
        "computer": {"on": True,
                     "detail": "shell enabled" if config.ALLOW_SHELL else "safe mode (shell off)"},
        "data": {"on": True, "detail": "key-free live APIs"},
    }


@app.get("/api/settings")
async def get_settings():
    return {
        "values": {
            "GEMINI_API_KEY": _mask(config.GEMINI_API_KEY),
            "GEMINI_MODEL": config.GEMINI_MODEL,
            "HA_URL": config.HA_URL,
            "HA_TOKEN": _mask(config.HA_TOKEN),
            "OCTOPRINT_URL": config.OCTOPRINT_URL,
            "OCTOPRINT_API_KEY": _mask(config.OCTOPRINT_API_KEY),
            "CUPS_PRINTER": config.CUPS_PRINTER,
            "WEATHER_LAT": config.WEATHER_LAT,
            "WEATHER_LON": config.WEATHER_LON,
            "ELEVENLABS_API_KEY": _mask(env_elevenlabs()),
            "ALLOW_SHELL": config.ALLOW_SHELL,
        },
        "services": await _service_checks(),
    }


def env_elevenlabs() -> str:
    import os
    return os.environ.get("ELEVENLABS_API_KEY", "").strip()


@app.post("/api/settings")
async def save_settings(updates: dict = Body(...)):
    """Save keys from the Settings panel, hot-reload config, rebuild Atlas."""
    global atlas
    # Ignore masked placeholders sent back unchanged, and blank secrets.
    cleaned = {k: v for k, v in updates.items()
               if isinstance(v, (str, int, float, bool)) and "••••" not in str(v)}
    if "ALLOW_SHELL" in cleaned:
        cleaned["ALLOW_SHELL"] = "true" if str(cleaned["ALLOW_SHELL"]).lower() in ("true", "1") else "false"
    changed = config.save(cleaned)
    if changed:
        atlas = Orchestrator()
        log.info("settings updated (%s) — Atlas rebuilt", ", ".join(changed))
    return {"changed": changed, "services": await _service_checks()}


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
            try:
                async for event in atlas.respond(session_id, text):
                    await ws.send_json(event)
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                # Never drop the connection over a model/tool failure.
                log.exception("turn failed")
                atlas.reset(session_id)
                await ws.send_json({
                    "type": "reply",
                    "text": f"Something went wrong on my end: {type(exc).__name__}. "
                            "Check the model name in settings, or just try again.",
                })
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
