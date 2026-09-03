"""WhatsApp Agent — the phone in Mehltani's hand.

Thin by design. All the protocol lives in integrations/whatsapp.py; this layer
exists to give the orchestrator tools it can reason about, and to enforce the
one rule that matters: messaging someone who is not you is an outward-facing,
irreversible act, so it goes through the guardian's `send_external` gate.
Messaging yourself does not — being nagged for a fingerprint to send yourself a
photo would make the whole loop useless.
"""
from __future__ import annotations

from .. import config, guardian
from ..integrations import whatsapp
from .base import BaseAgent, tool
from .scan_agent import latest_image, resolve_image


def _is_owner(recipient: str) -> bool:
    if not recipient.strip():
        return True
    normalise = lambda n: n.strip().lstrip("+").replace(" ", "").replace("-", "")  # noqa: E731
    return normalise(recipient) == normalise(config.WHATSAPP_OWNER)


class WhatsAppAgent(BaseAgent):
    name = "whatsapp"
    description = ("The phone: send messages, looks and photos to the owner's "
                   "WhatsApp, ask tap-to-answer questions, and read what has come "
                   "in. Messages to anyone other than the owner need a fingerprint.")

    @tool(
        "Send a WhatsApp message. Leave `to` blank to message the owner.",
        text={"type": "string", "description": "The message"},
        to={"type": "string", "description": "Phone number with country code; blank "
                                             "for the owner", "required": False},
        presence_token={"type": "string",
                        "description": "Biometric token, required for anyone other "
                                       "than the owner", "required": False},
    )
    async def send(self, text: str, to: str = "", presence_token: str = ""):
        if not _is_owner(to):
            try:
                guardian.require("send_external", presence_token=presence_token,
                                 detail={"channel": "whatsapp", "to": to})
            except guardian.Denied as exc:
                return {"needs_fingerprint": True, "error": str(exc)}
        return await whatsapp.send_text(text, to)

    @tool(
        "Send a photo from this machine to WhatsApp — a look, a rendered mockup, "
        "a scanned tear sheet.",
        caption={"type": "string", "description": "Caption for the image"},
        image_id={"type": "string", "description": "Photo id; blank uses newest",
                  "required": False},
        to={"type": "string", "description": "Recipient; blank for the owner",
            "required": False},
        presence_token={"type": "string", "description": "Biometric token for "
                                                         "external recipients",
                        "required": False},
    )
    async def send_photo(self, caption: str, image_id: str = "", to: str = "",
                         presence_token: str = ""):
        if not _is_owner(to):
            try:
                guardian.require("send_external", presence_token=presence_token,
                                 detail={"channel": "whatsapp", "to": to})
            except guardian.Denied as exc:
                return {"needs_fingerprint": True, "error": str(exc)}
        path = resolve_image(image_id) if image_id else latest_image()
        return await whatsapp.send_local_image(path, caption, to)

    @tool(
        "Ask a question with up to three tap-to-answer buttons. Much better than a "
        "plain message when you need a decision — one tap instead of typing.",
        question={"type": "string", "description": "The question"},
        options={"type": "string",
                 "description": "Comma-separated answers, max 3, 20 chars each"},
        to={"type": "string", "description": "Recipient; blank for the owner",
            "required": False},
    )
    async def ask(self, question: str, options: str, to: str = ""):
        choices = [o.strip() for o in options.split(",") if o.strip()][:3]
        if not choices:
            return {"error": "give at least one option"}
        return await whatsapp.send_choice(question, choices, to)

    @tool("Read recent WhatsApp messages that have come in since Mehltani started.",
          limit={"type": "string", "description": "How many, default 20",
                 "required": False})
    async def recent(self, limit: str = "20"):
        messages = whatsapp.recent(int(limit or 20))
        return {"count": len(messages), "messages": messages,
                "note": "the WhatsApp Cloud API has no history endpoint — this is "
                        "what has arrived since the last restart"}

    @tool("Check whether WhatsApp is connected and which number it is sending from.")
    async def status(self):
        state = await whatsapp.check()
        return {**state,
                "owner_number": config.WHATSAPP_OWNER or "(not set)",
                "webhook_path": "/api/whatsapp/webhook",
                "in_memory_thread": len(whatsapp.RECENT)}
