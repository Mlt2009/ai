"""Receipt / work-order slip layout — the printable artifact.

Renders a scanned receipt into the fixed-width slip your phone shortcut used
to build by hand, except the fields come from a real structured parse instead
of "take lines 15 to 28", so it survives a receipt whose layout moved.

Width defaults to 32 characters (58mm thermal roll); set RECEIPT_WIDTH=40 for
80mm, or 64 for plain letter paper on a laser printer.
"""
from __future__ import annotations

from datetime import date

from . import config

RULE_HEAVY = "="
RULE_LIGHT = "-"


def _center(text: str, width: int) -> str:
    text = text.strip()
    if len(text) >= width:
        return text[:width]
    return " " * ((width - len(text)) // 2) + text


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap; never drops a long word, splits it instead."""
    words, lines, current = str(text).split(), [], ""
    for word in words:
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _row(label: str, value: str, width: int) -> str:
    """`label ................. value`, clipped to the slip width."""
    value = str(value)
    space = width - len(value) - 1
    if space < 1:
        return value[:width]
    label = label[:space]
    return f"{label}{' ' * (width - len(label) - len(value))}{value}"


def _money(amount: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "$"}.get(currency, "")
    return f"{symbol}{float(amount or 0):,.2f}"


def render(receipt: dict, width: int | None = None, title: str = "") -> str:
    """Render one receipt dict (as stored by ledger.add_receipt) as a slip."""
    width = int(width or config.RECEIPT_WIDTH)
    width = max(24, min(width, 120))
    currency = receipt.get("currency") or "USD"
    lines: list[str] = []

    # ── header ────────────────────────────────────────────────────
    heading = title or config.BUSINESS_NAME or receipt.get("merchant") or "RECEIPT"
    for line in _wrap(heading.upper(), width):
        lines.append(_center(line, width))
    if config.BUSINESS_PHONE:
        lines.append(_center(config.BUSINESS_PHONE, width))
    lines.append(RULE_HEAVY * width)

    # ── meta ──────────────────────────────────────────────────────
    lines.append(_row("Date:", receipt.get("purchased_on") or date.today().isoformat(), width))
    if receipt.get("id"):
        lines.append(_row("Ref:", f"#{int(receipt['id']):04d}", width))
    merchant = receipt.get("merchant") or ""
    if merchant and merchant.upper() != heading.upper():
        lines.append(_row("Merchant:", merchant[: width - 11], width))
    if receipt.get("category"):
        lines.append(_row("Category:", receipt["category"], width))
    if receipt.get("payment_method"):
        lines.append(_row("Paid by:", receipt["payment_method"], width))

    # ── line items ────────────────────────────────────────────────
    items = receipt.get("items") or []
    if items:
        lines.append(RULE_LIGHT * width)
        for item in items:
            amount = _money(item.get("amount") or 0, currency)
            qty = str(item.get("qty") or "").strip()
            name = str(item.get("name") or item.get("description") or "item").strip()
            label = f"{qty} x {name}" if qty and qty not in ("1", "1.0") else name
            body = _wrap(label, max(4, width - len(amount) - 1))
            lines.append(_row(body[0], amount, width))
            lines.extend("  " + extra for extra in body[1:])

    # ── totals ────────────────────────────────────────────────────
    lines.append(RULE_LIGHT * width)
    if receipt.get("subtotal"):
        lines.append(_row("Subtotal", _money(receipt["subtotal"], currency), width))
    if receipt.get("tax"):
        lines.append(_row("Tax", _money(receipt["tax"], currency), width))
    lines.append(_row("TOTAL", _money(receipt.get("total") or 0, currency), width))
    lines.append(RULE_HEAVY * width)

    if receipt.get("note"):
        lines.extend(_wrap(receipt["note"], width))
        lines.append("")
    lines.append(_center(config.RECEIPT_FOOTER, width))
    return "\n".join(lines)


def render_invoice(invoice: dict, width: int | None = None) -> str:
    """Render an invoice as a printable slip — same paper, different heading."""
    width = max(32, min(int(width or config.RECEIPT_WIDTH), 120))
    currency = invoice.get("currency") or "USD"
    lines: list[str] = []

    heading = config.BUSINESS_NAME or "INVOICE"
    for line in _wrap(heading.upper(), width):
        lines.append(_center(line, width))
    if config.BUSINESS_PHONE:
        lines.append(_center(config.BUSINESS_PHONE, width))
    lines.append(_center("INVOICE", width))
    lines.append(RULE_HEAVY * width)

    lines.append(_row("Invoice:", invoice.get("number", ""), width))
    lines.append(_row("Issued:", invoice.get("issued_on") or date.today().isoformat(), width))
    if invoice.get("due_on"):
        lines.append(_row("Due:", invoice["due_on"], width))
    lines.append("")
    lines.append("BILL TO")
    lines.extend(_wrap(invoice.get("customer") or "(no customer)", width))
    for part in str(invoice.get("address") or "").splitlines():
        lines.extend(_wrap(part, width))

    lines.append(RULE_LIGHT * width)
    for item in invoice.get("items") or []:
        amount = _money(item.get("amount") or 0, currency)
        qty = str(item.get("qty") or "").strip()
        name = str(item.get("name") or "item").strip()
        label = f"{qty} x {name}" if qty and qty not in ("1", "1.0") else name
        body = _wrap(label, max(4, width - len(amount) - 1))
        lines.append(_row(body[0], amount, width))
        lines.extend("  " + extra for extra in body[1:])

    lines.append(RULE_LIGHT * width)
    lines.append(_row("Subtotal", _money(invoice.get("subtotal") or 0, currency), width))
    if invoice.get("tax"):
        pct = round(float(invoice.get("tax_rate") or 0) * 100, 2)
        lines.append(_row(f"Tax ({pct:g}%)", _money(invoice["tax"], currency), width))
    lines.append(_row("TOTAL DUE", _money(invoice.get("total") or 0, currency), width))
    lines.append(RULE_HEAVY * width)

    if invoice.get("paid"):
        lines.append(_center(f"PAID {invoice.get('paid_on', '')}".strip(), width))
    if invoice.get("note"):
        lines.extend(_wrap(invoice["note"], width))
    lines.append("")
    lines.append(_center(config.RECEIPT_FOOTER, width))
    return "\n".join(lines)
