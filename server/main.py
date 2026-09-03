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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import brain, config, guardian, ledger, receipt_layout, style_memory
from .agents import council_agent, scan_agent
from .integrations import glasses, google_ws, microsoft_ws, whatsapp
from .orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Mehltani")
atlas = Orchestrator()
guardian.snapshot_baseline()

# Paths that must stay reachable without a token, or you could never log in.
# The WhatsApp webhook is its own case: Meta calls it directly and cannot carry
# our ACCESS_TOKEN, so it is authenticated separately — verify-token on the GET
# handshake, HMAC signature on every POST (see integrations/whatsapp.py).
OPEN_PATHS = {"/", "/index.html", "/style.css", "/app.js", "/manifest.json",
              "/sw.js", "/icon.svg", "/api/auth", "/api/whatsapp/webhook"}


@app.middleware("http")
async def require_token(request: Request, call_next):
    """Gate every API call behind ACCESS_TOKEN, once one is set.

    With no token configured the server behaves exactly as before (fine on your
    own Wi-Fi). Set one before you expose it to the internet.
    """
    if config.ACCESS_TOKEN and request.url.path.startswith("/api/") \
            and request.url.path not in OPEN_PATHS:
        supplied = (request.headers.get("x-mehltani-token")
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
    return {"orchestrator": "Mehltani", "agents": atlas.team_roster()}


@app.get("/api/stats")
async def live_stats():
    """Lightweight live stats for the dashboard tiles."""
    vm = psutil.virtual_memory()
    return {
        "cpu": psutil.cpu_percent(interval=0.1),
        "mem": vm.percent,
        "gemini": bool(brain.provider()),
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
        "style": style_memory.stats(),
        "guardian": guardian.status(),
    }


@app.post("/api/broadcast")
async def broadcast(body: dict = Body(...)):
    """Ask every configured AI companion the same thing, straight from the UI."""
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    results = await council_agent.broadcast(prompt)
    return {"prompt": prompt, "results": results}


# ── style profile ────────────────────────────────────────────────

@app.get("/api/style")
async def style_profile():
    return {"summary": style_memory.summary(),
            "attributes": style_memory.attribute_scores()[:40],
            "traits": style_memory.list_traits(),
            "looks": style_memory.list_looks(limit=12),
            "verdicts": style_memory.list_verdicts(limit=20),
            "stats": style_memory.stats()}


@app.get("/api/style/scouted")
async def style_scouted(state: str = ""):
    items = style_memory.list_scouted(state=state)
    return {"count": len(items), "items": items}


# ── guardian: security dashboard ────────────────────────────────

@app.get("/api/guardian/status")
async def guardian_status():
    return guardian.status()


@app.post("/api/guardian/scan")
async def guardian_run_scan():
    return guardian.scan()


@app.get("/api/guardian/audit")
async def guardian_audit(limit: int = 50, denied_only: bool = False):
    return {"entries": guardian.audit_log(limit=limit, only_denied=denied_only)}


@app.get("/api/guardian/threats")
async def guardian_threats(unresolved_only: bool = False):
    return {"threats": guardian.threat_log(unresolved_only=unresolved_only)}


@app.post("/api/guardian/threats/{threat_id}/resolve")
async def guardian_resolve_threat(threat_id: int):
    return {"resolved": guardian.resolve_threat(threat_id)}


@app.post("/api/guardian/lockdown")
async def guardian_lockdown(body: dict = Body(default={})):
    return guardian.engage_lockdown(body.get("reason", "requested from dashboard"))


# ── guardian: WebAuthn (Touch ID / Face ID / Windows Hello / Android) ──
#
# Two independent ceremonies, both browser-driven — a model cannot trigger or
# satisfy either, which is the whole point (see guardian.py's module docstring).
# `finish_*` verifies the browser's response against the challenge issued by
# `begin_*`; a successful authentication mints a short-lived presence token the
# client then passes back as `presence_token` on a protected tool call.

@app.get("/api/guardian/biometrics")
async def guardian_biometrics():
    available, detail = guardian.biometrics_available()
    return {"available": available, "detail": detail,
            "enrolled": guardian.credentials(), "gate_on": config.REQUIRE_BIOMETRIC}


@app.post("/api/guardian/register/begin")
async def guardian_register_begin(body: dict = Body(default={})):
    try:
        return guardian.begin_registration(body.get("label", "my device"))
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/guardian/register/finish")
async def guardian_register_finish(body: dict = Body(...)):
    try:
        return guardian.finish_registration(
            body.get("state", ""), body.get("credential", {}),
            presence_token=body.get("presence_token", ""),
            recovery_key=body.get("recovery_key", ""))
    except guardian.Denied as exc:
        return JSONResponse({"error": str(exc), "needs_fingerprint": True}, status_code=403)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/guardian/verify/begin")
async def guardian_verify_begin(body: dict = Body(default={})):
    try:
        return guardian.begin_authentication(body.get("op", ""))
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/guardian/verify/finish")
async def guardian_verify_finish(body: dict = Body(...)):
    try:
        result = guardian.finish_authentication(body.get("state", ""),
                                                body.get("credential", {}))
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if body.get("op") == "lockdown_clear":
        guardian.clear_lockdown()
    return result


@app.delete("/api/guardian/devices/{credential_id}")
async def guardian_forget_device(credential_id: str):
    try:
        return {"removed": guardian.forget_credential(credential_id)}
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# ── WhatsApp webhook ─────────────────────────────────────────────
#
# Meta calls this directly, so it cannot carry our own ACCESS_TOKEN — see
# integrations/whatsapp.py for the verify-token handshake and HMAC signature
# check that authenticate it instead.

@app.get("/api/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    ok, body = whatsapp.verify_subscription(
        request.query_params.get("hub.mode", ""),
        request.query_params.get("hub.verify_token", ""),
        request.query_params.get("hub.challenge", ""))
    if not ok:
        guardian.raise_threat("whatsapp_webhook", body, severity="warn")
        return JSONResponse({"error": body}, status_code=403)
    return PlainTextResponse(body)


@app.post("/api/whatsapp/webhook")
async def whatsapp_incoming(request: Request):
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("x-hub-signature-256", "")):
        guardian.raise_threat("whatsapp_webhook", "signature verification failed",
                              severity="critical")
        return JSONResponse({"error": "bad signature"}, status_code=401)

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "bad payload"}, status_code=400)

    for message in whatsapp.parse_webhook(body):
        whatsapp.remember(message)
        await whatsapp.mark_read(message["id"])
        asyncio.create_task(_handle_whatsapp_message(message))
    return {"received": True}


async def _handle_whatsapp_message(message: dict) -> None:
    """Route an inbound WhatsApp message into the same brain as the voice channel.

    A tap on a "Love it" / "Pass" button is turned into a plain sentence before
    it reaches the orchestrator, so the same tool-calling loop that handles
    voice handles the approve/pass loop with no separate code path to drift
    out of sync.
    """
    text = message.get("text", "")
    if message.get("media_id") and not text:
        try:
            target = scan_agent.uploads_dir() / f"whatsapp_{message['id'][:16]}.jpg"
            await whatsapp.download_media(message["media_id"], target)
            text = (f"A photo just came in on WhatsApp (image_id: {target.name}). "
                    "Look at it and respond usefully — if it looks like a piece of "
                    "clothing or a look, offer a quick read; if it's a receipt, "
                    "offer to scan it.")
        except Exception as exc:
            log.warning("could not download WhatsApp media: %s", exc)
            return
    if message.get("button_reply"):
        text = f"On WhatsApp I just tapped: {message['button_reply']}"
    if not text.strip():
        return

    session_id = f"whatsapp:{message.get('from', 'unknown')}"
    try:
        async for event in atlas.respond(session_id, text):
            if event.get("type") == "reply" and event.get("text"):
                await whatsapp.send_text(event["text"], to=message.get("from", ""))
    except Exception:
        log.exception("WhatsApp turn failed")
        await whatsapp.send_text(
            "Something went wrong on my end handling that — try again in a moment.",
            to=message.get("from", ""))


# ── glasses ───────────────────────────────────────────────────────

@app.get("/api/glasses/status")
async def glasses_status():
    return glasses.status()


@app.post("/api/glasses/ingest")
async def glasses_ingest_now():
    return {"ingested": glasses.ingest()}


def _mask(secret: str) -> str:
    return f"••••{secret[-4:]}" if secret else ""


async def _service_checks() -> dict:
    """Live reachability tests for every integration (best-effort, fast)."""

    async def check_gemini():
        """The brain — Gemini or OpenAI, whichever key is configured."""
        try:
            return await asyncio.wait_for(brain.check(), timeout=8)
        except Exception as exc:
            return {"on": False, "detail": f"check failed: {type(exc).__name__}"}

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

    gemini, ha, octo, cups, wa, google, ms = await asyncio.gather(
        check_gemini(), check_ha(), check_octoprint(), check_cups(),
        whatsapp.check(), google_ws.check(), microsoft_ws.check())
    crew = council_agent.companions()
    names = ", ".join(c["name"] for c in crew)
    biometrics_on, biometrics_detail = guardian.biometrics_available()
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
        "whatsapp": wa,
        "google_workspace": google,
        "microsoft_365": ms,
        "glasses": {"on": glasses.watch_configured(),
                    "detail": glasses.status()["detail"]},
        "guardian": {"on": biometrics_on and len(guardian.credentials()) > 0,
                    "detail": (f"{len(guardian.credentials())} device(s) enrolled"
                              if biometrics_on and guardian.credentials()
                              else biometrics_detail)},
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
            "OWNER_NAME": config.OWNER_NAME,
            "RP_ID": config.RP_ID,
            "EXTRA_ORIGINS": config.EXTRA_ORIGINS,
            "REQUIRE_BIOMETRIC": config.REQUIRE_BIOMETRIC,
            "RECOVERY_KEY": _mask(config.RECOVERY_KEY),
            "AUTO_LOCKDOWN": config.AUTO_LOCKDOWN,
            "WHATSAPP_TOKEN": _mask(config.WHATSAPP_TOKEN),
            "WHATSAPP_PHONE_ID": config.WHATSAPP_PHONE_ID,
            "WHATSAPP_VERIFY_TOKEN": _mask(config.WHATSAPP_VERIFY_TOKEN),
            "WHATSAPP_APP_SECRET": _mask(config.WHATSAPP_APP_SECRET),
            "WHATSAPP_OWNER": config.WHATSAPP_OWNER,
            "GOOGLE_CLIENT_ID": config.GOOGLE_CLIENT_ID,
            "GOOGLE_CLIENT_SECRET": _mask(config.GOOGLE_CLIENT_SECRET),
            "GOOGLE_REFRESH_TOKEN": _mask(config.GOOGLE_REFRESH_TOKEN),
            "MS_CLIENT_ID": config.MS_CLIENT_ID,
            "MS_CLIENT_SECRET": _mask(config.MS_CLIENT_SECRET),
            "MS_TENANT": config.MS_TENANT,
            "MS_REFRESH_TOKEN": _mask(config.MS_REFRESH_TOKEN),
            "GLASSES_WATCH_DIR": config.GLASSES_WATCH_DIR,
            "GEMINI_IMAGE_MODEL": config.GEMINI_IMAGE_MODEL,
            "OPENAI_IMAGE_MODEL": config.OPENAI_IMAGE_MODEL,
        },
        "services": await _service_checks(),
    }


def env_elevenlabs() -> str:
    import os
    return os.environ.get("ELEVENLABS_API_KEY", "").strip()


@app.post("/api/settings")
async def save_settings(updates: dict = Body(...)):
    """Save keys from the Settings panel, hot-reload config, rebuild Mehltani."""
    global atlas
    # Ignore masked placeholders sent back unchanged, and blank secrets.
    cleaned = {k: v for k, v in updates.items()
               if isinstance(v, (str, int, float, bool)) and "••••" not in str(v)}
    for flag in ("ALLOW_SHELL", "ALLOW_FILE_WRITE", "REQUIRE_BIOMETRIC", "AUTO_LOCKDOWN"):
        if flag in cleaned:
            cleaned[flag] = "true" if str(cleaned[flag]).lower() in ("true", "1") else "false"
    changed = config.save(cleaned)
    if changed:
        atlas = Orchestrator()
        guardian.snapshot_baseline()
        log.info("settings updated (%s) — Mehltani rebuilt", ", ".join(changed))
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
    print("  MEHLTANI is online")
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
