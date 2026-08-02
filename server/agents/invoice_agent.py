"""Invoice Agent — bill the job, print it, chase what's owed.

The other side of the Scan agent: that one reads money going out, this one
tracks money coming in. Numbering is sequential per year (2026-0001), totals
are computed from the line items so they can't drift, and the printed sheet
uses the same paper as the receipt slips.
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import config, ledger, receipt_layout
from .base import BaseAgent, tool
from .scan_agent import print_slip


def _items_from(description: str) -> list[dict]:
    """Parse "labor 250, parts 80.50" into line items.

    Spoken invoices arrive as one phrase, so accept the loose form and let the
    amount be the last number in each part.
    """
    items = []
    for chunk in str(description).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        words = chunk.replace("$", "").split()
        amount, name_words = 0.0, words
        for index in range(len(words) - 1, -1, -1):
            try:
                amount = float(words[index].replace(",", ""))
                name_words = words[:index]
                break
            except ValueError:
                continue
        items.append({"name": " ".join(name_words) or "service", "qty": "1",
                      "amount": amount})
    return items


class InvoiceAgent(BaseAgent):
    name = "invoice"
    description = ("Bills customers: create and number invoices, print or PDF them, "
                   "mark them paid, and show what's still outstanding or overdue.")

    @tool(
        "Create an invoice for a customer.",
        customer={"type": "string", "description": "Who is being billed"},
        items={"type": "string",
               "description": "Line items as 'label amount' separated by commas, "
                              "e.g. 'main line snake 120, camera inspection 40'"},
        due_in_days={"type": "integer",
                     "description": "Payment terms in days (default from settings)",
                     "required": False},
        tax_rate={"type": "number",
                  "description": "Tax percent, e.g. 8.25 (default from settings)",
                  "required": False},
        email={"type": "string", "description": "Customer email", "required": False},
        address={"type": "string", "description": "Customer address", "required": False},
        note={"type": "string", "description": "Note printed on the invoice",
              "required": False},
    )
    async def create(self, customer: str, items: str, due_in_days: int = 0,
                     tax_rate: float = -1, email: str = "", address: str = "",
                     note: str = ""):
        parsed = _items_from(items)
        if not parsed:
            return {"error": "no line items could be read from that description"}
        days = int(due_in_days or config.INVOICE_TERMS_DAYS)
        rate = config.TAX_RATE if tax_rate is None or tax_rate < 0 else tax_rate
        invoice = ledger.add_invoice(
            customer=customer, items=parsed, email=email, address=address,
            due_on=(date.today() + timedelta(days=days)).isoformat(),
            tax_rate=rate, note=note)
        return {"invoice_id": invoice["id"], "number": invoice["number"],
                "customer": invoice["customer"], "subtotal": invoice["subtotal"],
                "tax": invoice["tax"], "total": invoice["total"],
                "due_on": invoice["due_on"], "line_items": len(invoice["items"])}

    @tool(
        "List invoices, newest first.",
        unpaid_only={"type": "boolean", "description": "Only what's still owed",
                     "required": False},
        customer={"type": "string", "description": "Filter by customer", "required": False},
        limit={"type": "integer", "description": "Max rows (default 20)", "required": False},
    )
    async def list_invoices(self, unpaid_only: bool = False, customer: str = "",
                            limit: int = 20):
        rows = ledger.list_invoices(unpaid_only=unpaid_only, customer=customer, limit=limit)
        return {"count": len(rows),
                "invoices": [{"id": r["id"], "number": r["number"],
                              "customer": r["customer"], "total": r["total"],
                              "due_on": r["due_on"], "paid": bool(r["paid"])}
                             for r in rows]}

    @tool("What's still owed, and how much of it is past due.")
    async def outstanding(self):
        return ledger.outstanding()

    @tool(
        "Mark an invoice as paid.",
        number={"type": "string", "description": "Invoice number, e.g. 2026-0004"},
        paid_on={"type": "string", "description": "ISO date; defaults to today",
                 "required": False},
    )
    async def mark_paid(self, number: str, paid_on: str = ""):
        invoice = ledger.find_invoice(number)
        if not invoice:
            return {"error": f"no invoice numbered {number!r}"}
        updated = ledger.mark_invoice_paid(invoice["id"], paid_on)
        return {"number": updated["number"], "customer": updated["customer"],
                "total": updated["total"], "paid_on": updated["paid_on"]}

    @tool(
        "Show an invoice as it will print, without printing it.",
        number={"type": "string", "description": "Invoice number"},
    )
    async def preview(self, number: str):
        invoice = ledger.find_invoice(number)
        if not invoice:
            return {"error": f"no invoice numbered {number!r}"}
        return {"number": invoice["number"],
                "slip": receipt_layout.render_invoice(invoice)}

    @tool(
        "Print an invoice on the paper printer.",
        number={"type": "string", "description": "Invoice number"},
        copies={"type": "integer", "description": "How many copies", "required": False},
    )
    async def print_invoice(self, number: str, copies: int = 1):
        invoice = ledger.find_invoice(number)
        if not invoice:
            return {"error": f"no invoice numbered {number!r}"}
        sheet = receipt_layout.render_invoice(invoice)
        result = await print_slip(sheet, title=f"invoice {invoice['number']}",
                                  copies=copies)
        return {"number": invoice["number"], "slip": sheet, "printed": result}

    @tool(
        "Write an invoice to a PDF file on this computer and return its path.",
        number={"type": "string", "description": "Invoice number"},
    )
    async def to_pdf(self, number: str):
        invoice = ledger.find_invoice(number)
        if not invoice:
            return {"error": f"no invoice numbered {number!r}"}
        from ..pdf import text_to_pdf

        target = await text_to_pdf(receipt_layout.render_invoice(invoice, width=64),
                                   f"invoice-{invoice['number']}")
        return {"number": invoice["number"], "pdf": target}
