"""WhatsApp Business Cloud API — the phone channel.

This is the most load-bearing integration in the system, for three reasons:

  1. It is how Mehltani reaches you when you are not at the computer: a look he
     scouted arrives as an image with a caption, and your reply trains the taste
     profile.
  2. It is the approve / pass loop. Interactive reply buttons make a verdict one
     tap instead of a sentence, which is the difference between a profile that
     learns every day and one that learns when you remember to.
  3. It is the realistic path from Meta glasses into this system — see
     glasses.py for why.

Setup, once, at developers.facebook.com:
  * create a Meta app, add the WhatsApp product
  * note the phone number ID and generate a permanent system-user token
  * point the webhook at https://<your host>/api/whatsapp/webhook and set the
    verify token to whatever you put in WHATSAPP_VERIFY_TOKEN
  * subscribe the app to the `messages` field

Note on the 24-hour rule: outside a 24-hour window opened by the user's own
message, Meta only delivers pre-approved template messages. Free-form sends will
come back with error 131047. `send_text` surfaces that verbatim instead of
pretending it worked.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from collections import deque
from pathlib import Path
from typing import Any

import httpx

from .. import config

log = logging.getLogger("whatsapp")

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = 45.0

# The Cloud API has no "fetch my history" endpoint — messages only ever arrive
# by webhook. So the thread is kept in memory here, populated as they land.
# Deliberately not persisted: it resets on restart, which is the honest
# behaviour rather than pretending to be a mailbox.
RECENT: deque[dict] = deque(maxlen=100)


def remember(message: dict) -> None:
    RECENT.appendleft(message)


def recent(limit: int = 20) -> list[dict]:
    return list(RECENT)[:limit]


def configured() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_ID)


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
            "content-type": "application/json"}


def _require() -> None:
    if not configured():
        raise RuntimeError(
            "WhatsApp is not connected — add WHATSAPP_TOKEN and WHATSAPP_PHONE_ID "
            "in Settings (Meta app > WhatsApp > API Setup)")


def _to(recipient: str = "") -> str:
    number = (recipient or config.WHATSAPP_OWNER).strip().lstrip("+").replace(" ", "")
    if not number:
        raise RuntimeError("no recipient — set WHATSAPP_OWNER to your own number")
    return number


# ── sending ───────────────────────────────────────────────────────

async def send_text(text: str, to: str = "") -> dict:
    _require()
    payload = {"messaging_product": "whatsapp", "to": _to(to), "type": "text",
               "text": {"preview_url": True, "body": text[:4096]}}
    return await _post(payload)


async def send_image(image_url: str, caption: str = "", to: str = "") -> dict:
    """Send an image by public URL — how a scouted look reaches your phone."""
    _require()
    payload = {"messaging_product": "whatsapp", "to": _to(to), "type": "image",
               "image": {"link": image_url, "caption": caption[:1024]}}
    return await _post(payload)


async def send_local_image(path: Path, caption: str = "", to: str = "") -> dict:
    """Upload a file from this machine, then send it.

    Used for anything Mehltani generated or that came off your own camera —
    those have no public URL, and exposing one just to message yourself would be
    a needless hole.
    """
    _require()
    media_id = await upload_media(path)
    payload = {"messaging_product": "whatsapp", "to": _to(to), "type": "image",
               "image": {"id": media_id, "caption": caption[:1024]}}
    return await _post(payload)


async def send_choice(body: str, options: list[str], to: str = "",
                      header: str = "") -> dict:
    """A message with up to three tap-to-answer buttons.

    The whole approve/pass loop rides on this: `send_choice("Yes?", ["Love it",
    "Pass", "Show me more"])`. Meta caps it at three buttons and 20 characters
    each, so longer options are truncated rather than rejected upstream.
    """
    _require()
    buttons = [{"type": "reply",
                "reply": {"id": f"opt_{i}", "title": str(option)[:20]}}
               for i, option in enumerate(options[:3])]
    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": buttons},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    payload = {"messaging_product": "whatsapp", "to": _to(to),
               "type": "interactive", "interactive": interactive}
    return await _post(payload)


async def _post(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(f"{GRAPH}/{config.WHATSAPP_PHONE_ID}/messages",
                                     headers=_headers(), json=payload)
    if response.status_code >= 400:
        body = response.json() if response.headers.get("content-type", "").startswith(
            "application/json") else {"raw": response.text[:300]}
        error = (body.get("error") or {})
        detail = error.get("message", "")
        if error.get("code") == 131047:
            detail += (" — this is Meta's 24-hour rule: send a message from your "
                       "phone to the business number first, then Mehltani can reply "
                       "freely for 24 hours.")
        return {"error": f"WhatsApp HTTP {response.status_code}: {detail or body}"}
    body = response.json()
    message_id = (body.get("messages") or [{}])[0].get("id", "")
    return {"sent": True, "message_id": message_id, "to": payload["to"]}


async def upload_media(path: Path) -> str:
    """Upload a local file and return its media id."""
    _require()
    import mimetypes

    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{GRAPH}/{config.WHATSAPP_PHONE_ID}/media",
            headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (path.name, path.read_bytes(), mime)})
        response.raise_for_status()
        return response.json()["id"]


async def download_media(media_id: str, destination: Path) -> Path:
    """Fetch inbound media — a photo you sent, or one from the glasses.

    Two hops by design on Meta's side: the id resolves to a short-lived signed
    URL, which then needs the same bearer token to actually read.
    """
    _require()
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        meta = await client.get(f"{GRAPH}/{media_id}", headers=_headers())
        meta.raise_for_status()
        url = meta.json().get("url")
        if not url:
            raise RuntimeError(f"no download URL for media {media_id}")
        blob = await client.get(url, headers={
            "Authorization": f"Bearer {config.WHATSAPP_TOKEN}"})
        blob.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blob.content)
    return destination


async def mark_read(message_id: str) -> dict:
    """Blue ticks. Small thing, but it makes the assistant feel present."""
    if not configured():
        return {"error": "not configured"}
    return await _post({"messaging_product": "whatsapp", "status": "read",
                        "message_id": message_id})


# ── receiving ─────────────────────────────────────────────────────

def verify_subscription(mode: str, token: str, challenge: str) -> tuple[bool, str]:
    """Meta's one-time webhook handshake (GET with hub.* params)."""
    if mode == "subscribe" and token and token == config.WHATSAPP_VERIFY_TOKEN:
        return True, challenge
    return False, "verification failed — WHATSAPP_VERIFY_TOKEN does not match"


def verify_signature(raw_body: bytes, header: str) -> bool:
    """Check X-Hub-Signature-256 so only Meta can drive the webhook.

    Skipped when no app secret is configured, which is fine on a private
    network and not fine on a public URL — check_exposure() flags that.
    """
    secret = config.WHATSAPP_APP_SECRET
    if not secret:
        return True
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(body: dict) -> list[dict]:
    """Flatten Meta's deeply nested payload into plain messages.

    Returns dicts of {id, from, type, text, media_id, button_reply, timestamp}.
    Status callbacks (delivered/read receipts) are dropped — they are noise for
    our purposes and would otherwise look like empty inbound messages.
    """
    out: list[dict] = []
    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                        for c in value.get("contacts") or []}
            for message in value.get("messages") or []:
                kind = message.get("type", "")
                parsed = {
                    "id": message.get("id", ""),
                    "from": message.get("from", ""),
                    "name": contacts.get(message.get("from", ""), ""),
                    "type": kind,
                    "timestamp": message.get("timestamp", ""),
                    "text": "",
                    "media_id": "",
                    "button_reply": "",
                }
                if kind == "text":
                    parsed["text"] = (message.get("text") or {}).get("body", "")
                elif kind in ("image", "audio", "video", "document", "sticker"):
                    media = message.get(kind) or {}
                    parsed["media_id"] = media.get("id", "")
                    parsed["text"] = media.get("caption", "")
                    parsed["mime"] = media.get("mime_type", "")
                elif kind == "interactive":
                    interactive = message.get("interactive") or {}
                    reply = (interactive.get("button_reply")
                             or interactive.get("list_reply") or {})
                    parsed["button_reply"] = reply.get("title", "")
                    parsed["text"] = reply.get("title", "")
                elif kind == "button":
                    parsed["button_reply"] = (message.get("button") or {}).get("text", "")
                    parsed["text"] = parsed["button_reply"]
                out.append(parsed)
    return out


async def check() -> dict:
    """Reachability probe for the Settings panel."""
    if not configured():
        return {"on": False, "detail": "no WHATSAPP_TOKEN / WHATSAPP_PHONE_ID"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{GRAPH}/{config.WHATSAPP_PHONE_ID}",
                                        headers=_headers())
        if response.status_code == 200:
            number = response.json().get("display_phone_number", "")
            return {"on": True, "detail": f"connected · {number or config.WHATSAPP_PHONE_ID}"}
        return {"on": False, "detail": f"HTTP {response.status_code}: "
                                       f"{response.text[:160]}"}
    except Exception as exc:
        return {"on": False, "detail": f"unreachable: {type(exc).__name__}"}
