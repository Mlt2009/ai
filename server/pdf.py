"""A tiny text-to-PDF writer — no dependencies.

Invoices and reports are already laid out as fixed-width text, so all a PDF
needs to do is put that text on a page in a monospaced font. Pillow can't do
that well and reportlab is a heavy dependency for one job, so this writes the
handful of PDF objects directly.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from . import config

PAGE_WIDTH, PAGE_HEIGHT = 612, 792     # US Letter, in points
MARGIN = 54                            # 0.75"
FONT_SIZE = 10
LINE_HEIGHT = 12.5
LINES_PER_PAGE = int((PAGE_HEIGHT - 2 * MARGIN) / LINE_HEIGHT)


def _escape(text: str) -> str:
    """Backslash, parens and non-Latin-1 characters break PDF literal strings."""
    out = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return "".join(char if ord(char) < 256 else "?" for char in out)


def _page_stream(lines: list[str]) -> bytes:
    parts = ["BT", f"/F1 {FONT_SIZE} Tf", f"{LINE_HEIGHT} TL",
             f"1 0 0 1 {MARGIN} {PAGE_HEIGHT - MARGIN} Tm"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", "replace")


def build(text: str) -> bytes:
    """Render fixed-width text as a paginated PDF document."""
    all_lines = text.splitlines() or [""]
    pages = [all_lines[i:i + LINES_PER_PAGE]
             for i in range(0, len(all_lines), LINES_PER_PAGE)] or [[""]]

    objects: list[bytes] = []          # 1-indexed on write
    page_count = len(pages)
    font_id = 3 + page_count * 2       # objects: 1 catalog, 2 pages, then page/content pairs

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())

    for index, page_lines in enumerate(pages):
        page_id = 3 + index * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Contents {page_id + 1} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        stream = _page_stream(page_lines)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                       + stream + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
                   b"/Encoding /WinAnsiEncoding >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


async def text_to_pdf(text: str, stem: str) -> str:
    """Write `text` to DATA_DIR/exports/<stem>.pdf and return the path."""
    out_dir = Path(config.DATA_DIR) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{Path(stem).name}.pdf"
    await asyncio.to_thread(target.write_bytes, build(text))
    return str(target)
