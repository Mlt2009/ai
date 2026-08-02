"""Mail Agent — send from the workspace, and skim what came in.

Plain SMTP and IMAP, so it works with Gmail (app password), Fastmail, your own
mail server, anything. Sending is the point: invoice out the door from the
phone, receipt to the bookkeeper, day sheet to a helper.
"""
from __future__ import annotations

import asyncio
import imaplib
import smtplib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from .. import config, ledger, receipt_layout
from ..pdf import text_to_pdf
from .base import BaseAgent, tool


def _require_smtp() -> None:
    if not (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD):
        raise RuntimeError("email isn't set up — add SMTP_HOST, SMTP_USER and "
                           "SMTP_PASSWORD in Settings (Gmail needs an app password)")


def _send(message: EmailMessage) -> None:
    """Blocking send; callers wrap this in a thread."""
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
        return
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(message)


def _build(to: str, subject: str, body: str, attachment: str = "") -> EmailMessage:
    message = EmailMessage()
    message["From"] = config.SMTP_FROM or config.SMTP_USER
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if attachment:
        path = Path(attachment)
        if not path.is_file():
            raise FileNotFoundError(f"no file at {attachment}")
        subtype = "pdf" if path.suffix.lower() == ".pdf" else "octet-stream"
        message.add_attachment(path.read_bytes(), maintype="application",
                               subtype=subtype, filename=path.name)
    return message


class MailAgent(BaseAgent):
    name = "mail"
    description = ("Sends and reads email: send a note or a file, email an invoice "
                   "straight to the customer as a PDF, and skim the inbox.")

    @tool(
        "Send an email, optionally with a file attached.",
        to={"type": "string", "description": "Recipient address"},
        subject={"type": "string", "description": "Subject line"},
        body={"type": "string", "description": "Message body"},
        attachment={"type": "string",
                    "description": "Full path to a file to attach", "required": False},
    )
    async def send(self, to: str, subject: str, body: str, attachment: str = ""):
        _require_smtp()
        message = _build(to, subject, body, attachment)
        await asyncio.to_thread(_send, message)
        return {"sent_to": to, "subject": subject,
                "attached": Path(attachment).name if attachment else None}

    @tool(
        "Email an invoice to the customer as a PDF attachment.",
        number={"type": "string", "description": "Invoice number, e.g. 2026-0004"},
        to={"type": "string",
            "description": "Override the address stored on the invoice", "required": False},
        message={"type": "string", "description": "Extra line in the body",
                 "required": False},
    )
    async def send_invoice(self, number: str, to: str = "", message: str = ""):
        _require_smtp()
        invoice = ledger.find_invoice(number)
        if not invoice:
            return {"error": f"no invoice numbered {number!r}"}
        address = to or invoice["email"]
        if not address:
            return {"error": f"invoice {number} has no email address — pass one in"}

        pdf_path = await text_to_pdf(
            receipt_layout.render_invoice(invoice, width=64),
            f"invoice-{invoice['number']}")
        business = config.BUSINESS_NAME or "us"
        body = (f"{message}\n\n" if message else "") + (
            f"Invoice {invoice['number']} for "
            f"{invoice['currency']} {invoice['total']:,.2f}"
            + (f", due {invoice['due_on']}" if invoice["due_on"] else "")
            + f".\n\nThe invoice is attached.\n\nThank you,\n{business}\n")
        email = _build(address, f"Invoice {invoice['number']} from {business}",
                       body, pdf_path)
        await asyncio.to_thread(_send, email)
        return {"invoice": invoice["number"], "sent_to": address, "pdf": pdf_path,
                "total": invoice["total"]}

    @tool(
        "Skim recent inbox messages (sender, subject, date).",
        limit={"type": "integer", "description": "How many, newest first (default 10)",
               "required": False},
        unread_only={"type": "boolean", "description": "Only unread", "required": False},
    )
    async def inbox(self, limit: int = 10, unread_only: bool = False):
        if not (config.IMAP_HOST and config.SMTP_USER and config.SMTP_PASSWORD):
            return {"error": "reading mail needs IMAP_HOST plus the SMTP_USER / "
                             "SMTP_PASSWORD credentials"}

        def fetch() -> list[dict]:
            limit_n = max(1, min(int(limit or 10), 50))
            with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as server:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.select("INBOX")
                _, data = server.search(None, "UNSEEN" if unread_only else "ALL")
                ids = (data[0] or b"").split()[-limit_n:]
                out = []
                for message_id in reversed(ids):
                    # BODY.PEEK leaves the message unread.
                    _, raw = server.fetch(message_id, "(BODY.PEEK[HEADER])")
                    if not raw or not isinstance(raw[0], tuple):
                        continue
                    headers = BytesParser(policy=policy.default).parsebytes(raw[0][1])
                    out.append({"from": str(headers.get("From", ""))[:120],
                                "subject": str(headers.get("Subject", ""))[:160],
                                "date": str(headers.get("Date", ""))})
                return out

        try:
            messages = await asyncio.to_thread(fetch)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
        return {"count": len(messages), "messages": messages}
