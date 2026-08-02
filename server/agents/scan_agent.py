"""Scan Agent — phone camera in, structured receipt + printed slip out.

Replaces the fragile phone-shortcut pipeline (OCR, split on newlines, take
lines 15–28) with a real parse: the photo goes to Gemini vision, comes back
as structured fields, gets stored in the ledger, rendered through the slip
layout, and pushed to the printer. Nothing depends on which line a value
happened to land on, so a different receipt layout doesn't break it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import shutil
import tempfile
from pathlib import Path

from .. import config, ledger, receipt_layout
from .base import BaseAgent, tool

EXTRACTION_PROMPT = """\
You are reading a photo of a receipt, invoice or work order. Return ONLY a
JSON object (no prose, no code fence) with exactly these keys:

{
  "merchant": string,          // business name printed on the document
  "purchased_on": string,      // ISO date YYYY-MM-DD; "" if not printed
  "subtotal": number,          // 0 if not printed
  "tax": number,               // 0 if not printed
  "total": number,             // the amount actually due/paid
  "currency": string,          // ISO code, e.g. "USD"
  "payment_method": string,    // e.g. "VISA ****1234", "" if unknown
  "category": string,          // one of: groceries, fuel, dining, supplies,
                               // tools, services, travel, utilities, other
  "items": [                   // one entry per line item; [] if none legible
    {"name": string, "qty": string, "amount": number}
  ],
  "note": string               // invoice/order number or reference, else ""
}

Rules: never invent a value you cannot read — use "" or 0 instead. Amounts are
plain numbers with no currency symbol or thousands separator. If the total is
handwritten, still read it.
"""


def uploads_dir() -> Path:
    path = Path(config.DATA_DIR) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_image(image_id: str) -> Path:
    """Map an image id to a file inside the uploads dir, refusing traversal."""
    name = Path(str(image_id).strip()).name  # drop any directory component
    if not name:
        raise ValueError("no image id given")
    path = (uploads_dir() / name).resolve()
    if path.parent != uploads_dir().resolve():
        raise ValueError("image id escapes the uploads directory")
    if not path.exists():
        raise FileNotFoundError(f"no upload named {name!r} — take a photo first")
    return path


def latest_image() -> Path:
    """The most recently uploaded photo — what "scan this" means by default."""
    shots = sorted(uploads_dir().glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not shots:
        raise FileNotFoundError("no photos uploaded yet — tap the camera button first")
    return shots[0]


def _parse_json(text: str) -> dict:
    """Tolerate a model that wraps its JSON in prose or a code fence."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _shrink(raw: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale a 12-megapixel phone photo before sending it upstream.

    Pillow is optional: without it the original bytes go up unchanged, which
    still works, just slower.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return raw, mime
    try:
        image = Image.open(io.BytesIO(raw))
        image.thumbnail((1600, 1600))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue(), "image/jpeg"
    except Exception:
        return raw, mime


class ScanAgent(BaseAgent):
    name = "scan"
    description = ("Reads photos taken on the phone: OCR, structured receipt/invoice "
                   "extraction into the finance ledger, PDF conversion, and printing "
                   "the formatted slip.")

    # ── Gemini vision ─────────────────────────────────────────────

    async def _vision(self, path: Path, prompt: str) -> str:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured (Settings ⚙)")
        from google import genai
        from google.genai import types

        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        raw, mime = _shrink(raw, mime)
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[types.Part.from_bytes(data=raw, mime_type=mime), prompt],
        )
        return (response.text or "").strip()

    # ── tools ─────────────────────────────────────────────────────

    @tool("List the photos taken on the phone that are ready to scan, newest first.")
    async def list_photos(self):
        shots = sorted(uploads_dir().glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {"photos": [{"image_id": p.name, "kb": round(p.stat().st_size / 1024)}
                           for p in shots[:20]]}

    @tool(
        "Read all the text out of a photo (OCR). Use when the user wants the raw words.",
        image_id={"type": "string",
                  "description": "Photo id from list_photos; omit for the newest photo",
                  "required": False},
    )
    async def read_text(self, image_id: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        text = await self._vision(
            path, "Transcribe every word visible in this image, preserving line breaks. "
                  "Return only the transcription.")
        return {"image_id": path.name, "text": text}

    @tool(
        "Scan a photographed receipt or invoice into structured fields and save it to "
        "the finance ledger. Returns the receipt id and the parsed amounts.",
        image_id={"type": "string",
                  "description": "Photo id from list_photos; omit for the newest photo",
                  "required": False},
        category={"type": "string",
                  "description": "Override the auto-detected category", "required": False},
    )
    async def scan_receipt(self, image_id: str = "", category: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        raw_text = await self._vision(path, EXTRACTION_PROMPT)
        try:
            parsed = _parse_json(raw_text)
        except json.JSONDecodeError:
            return {"error": "could not read that photo as a receipt — try a "
                             "straighter, better-lit shot",
                    "image_id": path.name}
        receipt = ledger.add_receipt(
            merchant=str(parsed.get("merchant") or ""),
            total=parsed.get("total"),
            purchased_on=str(parsed.get("purchased_on") or ""),
            subtotal=parsed.get("subtotal"),
            tax=parsed.get("tax"),
            currency=str(parsed.get("currency") or "USD"),
            category=category or str(parsed.get("category") or "other"),
            payment_method=str(parsed.get("payment_method") or ""),
            note=str(parsed.get("note") or ""),
            items=parsed.get("items") or [],
            raw_text=raw_text,
            image_id=path.name,
            source="scan",
        )
        return {"receipt_id": receipt["id"], "merchant": receipt["merchant"],
                "total": receipt["total"], "date": receipt["purchased_on"],
                "category": receipt["category"], "items": len(receipt["items"])}

    @tool(
        "Take the photo, scan it, lay it out as a printable slip and send it to the "
        "paper printer — the whole picture-to-print pipeline in one step.",
        image_id={"type": "string",
                  "description": "Photo id from list_photos; omit for the newest photo",
                  "required": False},
        title={"type": "string",
               "description": "Heading printed at the top of the slip", "required": False},
        copies={"type": "integer", "description": "How many copies", "required": False},
    )
    async def scan_and_print(self, image_id: str = "", title: str = "", copies: int = 1):
        scanned = await self.scan_receipt(image_id=image_id)
        if "error" in scanned:
            return scanned
        receipt = ledger.get_receipt(scanned["receipt_id"])
        slip = receipt_layout.render(receipt, title=title)
        printed = await print_slip(slip, title=title or receipt["merchant"] or "receipt",
                                   copies=copies)
        return {**scanned, "slip": slip, "printed": printed}

    @tool(
        "Show the formatted slip for a saved receipt without printing it.",
        receipt_id={"type": "integer", "description": "Receipt id from scan_receipt"},
        title={"type": "string", "description": "Heading override", "required": False},
    )
    async def preview_slip(self, receipt_id: int, title: str = ""):
        receipt = ledger.get_receipt(int(receipt_id))
        if not receipt:
            return {"error": f"no receipt #{receipt_id}"}
        return {"receipt_id": receipt["id"], "slip": receipt_layout.render(receipt, title=title)}

    @tool(
        "Convert a photo into a PDF file on this computer and return its path.",
        image_id={"type": "string", "description": "Photo id; omit for the newest photo",
                  "required": False},
    )
    async def to_pdf(self, image_id: str = ""):
        path = resolve_image(image_id) if image_id else latest_image()
        try:
            from PIL import Image
        except ImportError:
            return {"error": "PDF conversion needs Pillow — run: pip install pillow"}
        out = Path(config.DATA_DIR) / "exports"
        out.mkdir(parents=True, exist_ok=True)
        target = out / (path.stem + ".pdf")
        image = Image.open(path)
        if image.mode != "RGB":
            image = image.convert("RGB")
        await asyncio.to_thread(image.save, target, "PDF", resolution=150)
        return {"pdf": str(target), "image_id": path.name}


async def print_slip(text: str, title: str = "slip", copies: int = 1) -> dict:
    """Send rendered text to the default paper printer (CUPS on Linux/macOS,
    the print verb on Windows). Shared by the Scan and Finance agents."""
    copies = max(1, min(int(copies or 1), 10))
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(text + "\n\n\n")
        temp = handle.name

    copies_handled = False
    if shutil.which("lp"):
        cmd = ["lp", "-t", title[:64], "-n", str(copies)]
        copies_handled = True
        if config.CUPS_PRINTER:
            cmd += ["-d", config.CUPS_PRINTER]
        cmd.append(temp)
    elif shutil.which("powershell"):  # Windows fallback
        # The path goes through the environment, never interpolated into the script.
        printer = ' -Name $env:ATLAS_PRINTER' if config.CUPS_PRINTER else ""
        cmd = ["powershell", "-NoProfile", "-Command",
               f"1..$env:ATLAS_COPIES | ForEach-Object {{ Get-Content -LiteralPath "
               f"$env:ATLAS_PRINT_FILE | Out-Printer{printer} }}"]
        copies_handled = True
    else:
        return {"ok": False, "error": "no printer command found (install CUPS, "
                                      "or run this server on the machine with the printer)"}

    env = {**_print_env(), "ATLAS_PRINT_FILE": temp, "ATLAS_COPIES": str(copies),
           "ATLAS_PRINTER": config.CUPS_PRINTER}
    runs = 1 if copies_handled else copies
    for _ in range(runs):
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return {"ok": False, "error": err.decode(errors="replace").strip()}
    return {"ok": True, "job": out.decode(errors="replace").strip() or "sent to printer",
            "copies": copies}


def _print_env() -> dict:
    import os

    return dict(os.environ)
