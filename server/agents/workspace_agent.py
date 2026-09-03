"""Workspace Agent — Gmail, Drive, Calendar, Outlook, OneDrive and Teams.

One agent over both suites rather than two, because you do not think in terms
of "which vendor holds this email" — you think "did the fabric supplier reply".
So every tool takes a `where` of google, microsoft or both, and `both` is the
default for reads. Writes always name one, since silently sending the same mail
from two addresses would be its own kind of disaster.

Sending mail is gated behind the guardian's `send_external` check. Reading is
not: an assistant that asks for a fingerprint to check the inbox is an assistant
you stop using by Thursday.
"""
from __future__ import annotations

import asyncio

from .. import brain, guardian
from ..integrations import google_ws, microsoft_ws
from .base import BaseAgent, tool


async def _gather(where: str, google_call, microsoft_call) -> dict:
    """Run whichever back ends are asked for, tolerating one being down."""
    where = (where or "both").lower()
    tasks: dict[str, asyncio.Future] = {}
    if where in ("both", "google") and google_ws.configured():
        tasks["google"] = asyncio.ensure_future(google_call())
    if where in ("both", "microsoft", "ms") and microsoft_ws.configured():
        tasks["microsoft"] = asyncio.ensure_future(microsoft_call())

    if not tasks:
        return {"error": "neither workspace is connected — add Google or Microsoft "
                         "credentials in Settings",
                "google": google_ws.configured(),
                "microsoft": microsoft_ws.configured()}

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out: dict = {}
    for name, result in zip(tasks, results):
        if isinstance(result, Exception):
            out[name] = {"error": f"{type(result).__name__}: {str(result)[:200]}"}
        else:
            out[name] = result
    return out


class WorkspaceAgent(BaseAgent):
    name = "workspace"
    description = ("The business inbox and files: Gmail and Outlook mail, Google "
                   "Drive and OneDrive, both calendars, and Teams chat. Reads "
                   "across both suites at once; sending needs a fingerprint.")

    # ── mail ──────────────────────────────────────────────────────

    @tool(
        "Search or list email across Gmail and Outlook. Use for 'any word from the "
        "supplier', 'what's unread', 'find the invoice from the studio'.",
        query={"type": "string",
               "description": "Search terms. Gmail syntax works for Google "
                              "(is:unread, from:...). Blank lists the inbox.",
               "required": False},
        limit={"type": "string", "description": "How many, default 10",
               "required": False},
        where={"type": "string", "description": "google, microsoft or both",
               "required": False},
    )
    async def mail(self, query: str = "", limit: str = "10", where: str = "both"):
        count = int(limit or 10)
        gmail_query = query or "in:inbox"
        return await _gather(
            where,
            lambda: google_ws.list_mail(gmail_query, count),
            lambda: microsoft_ws.list_mail(query, count))

    @tool(
        "Send an email. Requires the owner's fingerprint — mail leaves the building "
        "and cannot be recalled.",
        to={"type": "string", "description": "Recipient address"},
        subject={"type": "string", "description": "Subject line"},
        body={"type": "string", "description": "Message body, plain text"},
        where={"type": "string", "description": "google or microsoft",
               "required": False},
        cc={"type": "string", "description": "CC addresses", "required": False},
        presence_token={"type": "string", "description": "Biometric token",
                        "required": False},
    )
    async def send_email(self, to: str, subject: str, body: str, where: str = "google",
                         cc: str = "", presence_token: str = ""):
        try:
            guardian.require("send_external", presence_token=presence_token,
                             detail={"channel": "email", "to": to, "subject": subject})
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc),
                    "draft": {"to": to, "subject": subject, "body": body}}
        if where.lower().startswith("m"):
            return await microsoft_ws.send_mail(to, subject, body, cc)
        return await google_ws.send_mail(to, subject, body, cc=cc)

    @tool(
        "Draft a reply to an email without sending it, in the owner's voice.",
        message_id={"type": "string", "description": "The message to reply to"},
        intent={"type": "string", "description": "What the reply should say"},
        where={"type": "string", "description": "google or microsoft",
               "required": False},
    )
    async def draft_reply(self, message_id: str, intent: str, where: str = "google"):
        if where.lower().startswith("m"):
            found = await microsoft_ws.list_mail(limit=40)
            original = next((m for m in found if m["id"] == message_id), None)
        else:
            found = await google_ws.list_mail("in:anywhere", 40)
            original = next((m for m in found if m["id"] == message_id), None)
        if not original:
            return {"error": f"could not find message {message_id}"}
        draft = await brain.complete(
            "Draft a reply to this email. Match the register of the original — "
            "professional but human, no corporate filler, no markdown. Sign off "
            "simply.\n\n"
            f"FROM: {original.get('from')}\nSUBJECT: {original.get('subject')}\n"
            f"BODY:\n{original.get('body') or original.get('snippet')}\n\n"
            f"THE REPLY SHOULD: {intent}")
        return {"reply_to": message_id, "to": original.get("from"),
                "subject": f"Re: {original.get('subject', '')}", "draft": draft,
                "next": "call workspace__send_email to send it — that needs a fingerprint"}

    @tool(
        "Triage the inbox: what actually needs the owner, what can wait, what is "
        "noise. Use for 'anything important' or a morning catch-up.",
        limit={"type": "string", "description": "How many to read, default 20",
               "required": False},
    )
    async def triage(self, limit: str = "20"):
        mail = await self.mail(query="is:unread", limit=limit)
        messages = []
        for suite in ("google", "microsoft"):
            found = mail.get(suite)
            if isinstance(found, list):
                messages.extend({**m, "suite": suite} for m in found)
        if not messages:
            return {"clear": True, "note": "nothing unread across the connected suites"}
        digest = "\n\n".join(
            f"[{m['suite']}:{m['id'][:10]}] From {m.get('from')} — "
            f"{m.get('subject')}\n{(m.get('snippet') or '')[:300]}"
            for m in messages[:25])
        summary = await brain.complete(
            "Triage this inbox for a working fashion stylist and designer. Sort into "
            "three groups: needs them today, can wait, ignorable. For each item in "
            "the first group give one line on what it wants and the smallest next "
            "action. Be blunt about what is noise. Plain prose, no markdown.\n\n"
            + digest)
        return {"unread": len(messages), "triage": summary}

    # ── files ─────────────────────────────────────────────────────

    @tool(
        "Search Google Drive and OneDrive for a file.",
        query={"type": "string", "description": "Filename or fragment"},
        where={"type": "string", "description": "google, microsoft or both",
               "required": False},
    )
    async def files(self, query: str, where: str = "both"):
        return await _gather(where,
                             lambda: google_ws.search_drive(query),
                             lambda: microsoft_ws.search_drive(query))

    @tool(
        "Save text to the cloud — a call sheet, a lookbook, an invoice.",
        name={"type": "string", "description": "Filename including extension"},
        content={"type": "string", "description": "The text to save"},
        where={"type": "string", "description": "google or microsoft",
               "required": False},
        folder={"type": "string", "description": "Destination folder",
                "required": False},
    )
    async def save_file(self, name: str, content: str, where: str = "google",
                        folder: str = "Mehltani"):
        raw = content.encode()
        if where.lower().startswith("m"):
            return await microsoft_ws.upload_file(name, raw, folder)
        return await google_ws.upload_to_drive(name, raw, "text/plain")

    # ── calendar ──────────────────────────────────────────────────

    @tool(
        "What is coming up — shoots, fittings, client appointments — across both "
        "calendars.",
        days={"type": "string", "description": "How many days ahead, default 7",
              "required": False},
        where={"type": "string", "description": "google, microsoft or both",
               "required": False},
    )
    async def schedule(self, days: str = "7", where: str = "both"):
        ahead = int(days or 7)
        return await _gather(where,
                             lambda: google_ws.list_events(ahead),
                             lambda: microsoft_ws.list_events(ahead))

    @tool(
        "Book something in the calendar — a shoot, a fitting, a consultation.",
        summary={"type": "string", "description": "What it is"},
        start={"type": "string", "description": "ISO 8601 start, e.g. "
                                                "2026-08-14T10:00:00Z"},
        end={"type": "string", "description": "ISO 8601 end"},
        where={"type": "string", "description": "google or microsoft",
               "required": False},
        location={"type": "string", "description": "Where", "required": False},
        notes={"type": "string", "description": "Details", "required": False},
        attendees={"type": "string", "description": "Comma-separated emails",
                   "required": False},
    )
    async def book(self, summary: str, start: str, end: str, where: str = "google",
                   location: str = "", notes: str = "", attendees: str = ""):
        guests = [a.strip() for a in attendees.split(",") if a.strip()]
        if guests:
            # Inviting people is outward-facing, but a calendar invite is far
            # less consequential than an email and trivially cancellable, so it
            # is logged rather than gated.
            guardian.audit("calendar_invite", True,
                           detail={"summary": summary, "attendees": guests})
        if where.lower().startswith("m"):
            return await microsoft_ws.create_event(
                summary, start, end, location=location, description=notes,
                attendees=guests)
        return await google_ws.create_event(
            summary, start, end, location=location, description=notes,
            attendees=guests)

    # ── Teams ─────────────────────────────────────────────────────

    @tool("List recent Teams chats.")
    async def teams_chats(self):
        if not microsoft_ws.configured():
            return {"error": "Microsoft 365 is not connected"}
        chats = await microsoft_ws.list_teams_chats()
        return {"count": len(chats), "chats": chats}

    @tool(
        "Send a Teams message. Needs a fingerprint — it goes to other people.",
        chat_id={"type": "string", "description": "Chat id from teams_chats"},
        text={"type": "string", "description": "The message"},
        presence_token={"type": "string", "description": "Biometric token",
                        "required": False},
    )
    async def teams_send(self, chat_id: str, text: str, presence_token: str = ""):
        try:
            guardian.require("send_external", presence_token=presence_token,
                             detail={"channel": "teams", "chat": chat_id})
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc)}
        return await microsoft_ws.send_teams_message(chat_id, text)

    @tool("Check which workspaces are connected.")
    async def status(self):
        google, microsoft = await asyncio.gather(google_ws.check(), microsoft_ws.check())
        return {"google": google, "microsoft": microsoft}
