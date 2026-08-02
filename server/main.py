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
from fastapi import Body, FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, ledger, receipt_layout
from .agents import council_agent, scan_agent
from .orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="AI Companion")
atlas = Orchestrator()

# Paths that must stay reachable without a token, or you could never log in.
OPEN_PATHS = {"/", "/index.html", "/style.css", "/app.js", "/manifest.json",
              "/sw.js", "/icon.svg", "/api/auth"}


@app.middleware("http")
async def require_token(request: Request, call_next):
    """Gate every API call behind ACCESS_TOKEN, once one is set.

    With no token configured the server behaves exactly as before (fine on your
    own Wi-Fi). Set one before you expose it to the internet.
    """
    if config.ACCESS_TOKEN and request.url.path.startswith("/api/") \
            and request.url.path not in OPEN_PATHS:
        supplied = (request.headers.get("x-atlas-token")
                    or request.query_params.get("token", ""))
        if supplied != config.ACCESS_TOKEN:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/auth")
async def auth_needed(token: str = ""):
    """Does this server want a token, and is the one I have correct?"""
    return {"required": bool(config.ACCESS_TOKEN),
            "ok": not config.ACCESS_TOKEN or token == config.ACCESS_TOKEN}


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


@app.post("/api/upload")
async def upload_photo(photo: UploadFile = File(...)):
    """Receive a photo straight from the phone camera."""
    suffix = Path(photo.filename or "shot.jpg").suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"}:
        return JSONResponse({"error": f"unsupported image type {suffix}"}, status_code=400)
    image_id = f"{uuid.uuid4().hex[:12]}{suffix}"
    target = scan_agent.uploads_dir() / image_id
    target.write_bytes(await photo.read())
    log.info("photo uploaded: %s (%d KB)", image_id, target.stat().st_size // 1024)
    return {"image_id": image_id, "kb": round(target.stat().st_size / 1024)}


@app.post("/api/scan")
async def scan_photo(body: dict = Body(default={})):
    """One-tap pipeline: newest photo → OCR → layout → (optionally) print."""
    agent = atlas.agents.get("scan")
    if agent is None:
        return JSONResponse({"error": "scan agent unavailable"}, status_code=500)
    if body.get("print"):
        return await agent.call("scan_and_print", {
            "image_id": body.get("image_id", ""), "title": body.get("title", ""),
            "copies": int(body.get("copies") or 1)})
    result = await agent.call("scan_receipt", {"image_id": body.get("image_id", "")})
    if isinstance(result, dict) and result.get("receipt_id"):
        receipt = ledger.get_receipt(result["receipt_id"])
        result["slip"] = receipt_layout.render(receipt, title=body.get("title", ""))
    return result


@app.get("/api/workspace")
async def workspace():
    """Everything the workspace grid renders: agents, companions, money."""
    from datetime import date

    month_start = date.today().replace(day=1).isoformat()
    spend = ledger.totals("category", since=month_start)
    return {
        "agents": atlas.team_roster(),
        "companions": [{"name": c["name"], "model": c["model"], "kind": c["kind"]}
                       for c in council_agent.companions()],
        "month": {
            "since": month_start,
            "total": round(sum(g["total"] or 0 for g in spend), 2),
            "by_category": spend[:6],
        },
        "recent": [{"id": r["id"], "date": r["purchased_on"], "merchant": r["merchant"],
                    "total": r["total"], "category": r["category"]}
                   for r in ledger.list_receipts(limit=8)],
        "shopping": ledger.list_items()[:12],
        "photos": sorted((p.name for p in scan_agent.uploads_dir().glob("*.*")),
                         reverse=True)[:6],
    }


@app.post("/api/broadcast")
async def broadcast(body: dict = Body(...)):
    """Ask every configured AI companion the same thing, straight from the UI."""
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    results = await council_agent.broadcast(prompt)
    return {"prompt": prompt, "results": results}


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
    crew = council_agent.companions()
    names = ", ".join(c["name"] for c in crew)
    return {
        "gemini": gemini,
        "home_assistant": ha,
        "octoprint": octo,
        "cups": cups,
        "computer": {"on": True,
                     "detail": "shell enabled" if config.ALLOW_SHELL else "safe mode (shell off)"},
        "data": {"on": True, "detail": "key-free live APIs"},
        "council": {"on": bool(crew),
                    "detail": f"{len(crew)} companion(s): {names}" if crew
                              else "no AI companions configured yet"},
        "files": {"on": True,
                  "detail": ("read + write" if config.ALLOW_FILE_WRITE else "read only")
                            + f" · {config.FILE_ROOTS}"},
        "remote": {"on": bool(config.ACCESS_TOKEN),
                   "detail": "access token set" if config.ACCESS_TOKEN
                             else "no token — keep this on your own network"},
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
            "ANTHROPIC_API_KEY": _mask(config.ANTHROPIC_API_KEY),
            "ANTHROPIC_MODEL": config.ANTHROPIC_MODEL,
            "OPENAI_API_KEY": _mask(config.OPENAI_API_KEY),
            "OPENAI_MODEL": config.OPENAI_MODEL,
            "OPENROUTER_API_KEY": _mask(config.OPENROUTER_API_KEY),
            "OPENROUTER_MODEL": config.OPENROUTER_MODEL,
            "COMPANION_ENDPOINTS": config.COMPANION_ENDPOINTS,
            "BUSINESS_NAME": config.BUSINESS_NAME,
            "BUSINESS_PHONE": config.BUSINESS_PHONE,
            "RECEIPT_WIDTH": config.RECEIPT_WIDTH,
            "RECEIPT_FOOTER": config.RECEIPT_FOOTER,
            "FILE_ROOTS": config.FILE_ROOTS,
            "ALLOW_FILE_WRITE": config.ALLOW_FILE_WRITE,
            "ACCESS_TOKEN": _mask(config.ACCESS_TOKEN),
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
    for flag in ("ALLOW_SHELL", "ALLOW_FILE_WRITE"):
        if flag in cleaned:
            cleaned[flag] = "true" if str(cleaned[flag]).lower() in ("true", "1") else "false"
    changed = config.save(cleaned)
    if changed:
        atlas = Orchestrator()
        log.info("settings updated (%s) — Atlas rebuilt", ", ".join(changed))
    return {"changed": changed, "services": await _service_checks()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if config.ACCESS_TOKEN and ws.query_params.get("token", "") != config.ACCESS_TOKEN:
        await ws.close(code=1008)
        return
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
