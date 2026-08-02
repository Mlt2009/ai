"""Finance Agent — the professional workspace side: expenses, budgets, reports."""
from __future__ import annotations

import asyncio
import csv
from datetime import date, timedelta
from pathlib import Path

from .. import config, ledger, receipt_layout
from .base import BaseAgent, tool
from .scan_agent import print_slip


def _month_start() -> str:
    return date.today().replace(day=1).isoformat()


class FinanceAgent(BaseAgent):
    name = "finance"
    description = ("The finance workspace: record and query expenses, spend summaries by "
                   "category/merchant/month, budgets, tax-year totals, CSV export, and "
                   "printing receipts or expense reports.")

    @tool(
        "Record an expense by hand (no photo needed).",
        merchant={"type": "string", "description": "Who was paid"},
        total={"type": "number", "description": "Amount paid"},
        category={"type": "string",
                  "description": "e.g. groceries, fuel, tools, services", "required": False},
        purchased_on={"type": "string",
                      "description": "ISO date YYYY-MM-DD; defaults to today", "required": False},
        payment_method={"type": "string", "description": "Card or account", "required": False},
        note={"type": "string", "description": "Reference or memo", "required": False},
    )
    async def record_expense(self, merchant: str, total: float, category: str = "other",
                             purchased_on: str = "", payment_method: str = "",
                             note: str = ""):
        receipt = ledger.add_receipt(
            merchant=merchant, total=total, category=category, purchased_on=purchased_on,
            payment_method=payment_method, note=note, source="manual")
        return {"receipt_id": receipt["id"], "merchant": receipt["merchant"],
                "total": receipt["total"], "date": receipt["purchased_on"],
                "category": receipt["category"]}

    @tool(
        "List recorded expenses, newest first.",
        since={"type": "string", "description": "ISO date lower bound", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
        category={"type": "string", "description": "Filter by category", "required": False},
        merchant={"type": "string", "description": "Filter by merchant (substring)",
                  "required": False},
        limit={"type": "integer", "description": "Max rows (default 20)", "required": False},
    )
    async def list_expenses(self, since: str = "", until: str = "", category: str = "",
                            merchant: str = "", limit: int = 20):
        rows = ledger.list_receipts(since=since, until=until, category=category,
                                    merchant=merchant, limit=limit)
        return {"count": len(rows),
                "expenses": [{"id": r["id"], "date": r["purchased_on"],
                              "merchant": r["merchant"], "total": r["total"],
                              "category": r["category"]} for r in rows]}

    @tool(
        "Total spending grouped by category, merchant or month.",
        group_by={"type": "string", "description": "'category', 'merchant' or 'month'",
                  "required": False},
        since={"type": "string", "description": "ISO date lower bound; defaults to "
                                                "the start of this month", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
    )
    async def spend_summary(self, group_by: str = "category", since: str = "", until: str = ""):
        since = since or _month_start()
        groups = ledger.totals(group_by=group_by, since=since, until=until)
        return {"since": since, "until": until or "today", "group_by": group_by,
                "grand_total": round(sum(g["total"] or 0 for g in groups), 2),
                "groups": groups}

    @tool(
        "Set a monthly spending limit for a category.",
        category={"type": "string", "description": "Category name"},
        monthly_limit={"type": "number", "description": "Limit in your currency"},
    )
    async def set_budget(self, category: str, monthly_limit: float):
        return ledger.set_budget(category, monthly_limit)

    @tool(
        "Show this month's spend against every budget — what's left, what's over.",
        month={"type": "string", "description": "YYYY-MM; defaults to this month",
               "required": False},
    )
    async def budget_status(self, month: str = ""):
        rows = ledger.budget_status(month)
        over = [r["category"] for r in rows if r["over_budget"]]
        return {"month": month or date.today().strftime("%Y-%m"),
                "budgets": rows, "over_budget": over}

    @tool(
        "Deductible-style totals by category for a tax year.",
        year={"type": "integer", "description": "Four-digit year; defaults to this year",
              "required": False},
    )
    async def tax_summary(self, year: int = 0):
        year = int(year or date.today().year)
        groups = ledger.totals("category", since=f"{year}-01-01", until=f"{year}-12-31")
        return {"year": year, "total": round(sum(g["total"] or 0 for g in groups), 2),
                "by_category": groups}

    @tool(
        "Export expenses to a CSV file on this computer and return its path.",
        since={"type": "string", "description": "ISO date lower bound", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
    )
    async def export_csv(self, since: str = "", until: str = ""):
        rows = ledger.list_receipts(since=since, until=until, limit=500)
        out = Path(config.DATA_DIR) / "exports"
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"expenses-{date.today().isoformat()}.csv"
        columns = ["id", "purchased_on", "merchant", "category", "subtotal", "tax",
                   "total", "currency", "payment_method", "note", "source"]

        def write() -> None:
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

        await asyncio.to_thread(write)
        return {"csv": str(target), "rows": len(rows)}

    @tool(
        "Print a saved receipt as a formatted slip on the paper printer.",
        receipt_id={"type": "integer", "description": "Receipt id"},
        title={"type": "string", "description": "Heading override", "required": False},
        copies={"type": "integer", "description": "How many copies", "required": False},
    )
    async def print_receipt(self, receipt_id: int, title: str = "", copies: int = 1):
        receipt = ledger.get_receipt(int(receipt_id))
        if not receipt:
            return {"error": f"no receipt #{receipt_id}"}
        slip = receipt_layout.render(receipt, title=title)
        result = await print_slip(slip, title=title or receipt["merchant"] or "receipt",
                                  copies=copies)
        return {"receipt_id": receipt["id"], "slip": slip, "printed": result}

    @tool(
        "Print an expense report for a date range on the paper printer.",
        since={"type": "string", "description": "ISO date lower bound; defaults to "
                                                "30 days ago", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
    )
    async def print_report(self, since: str = "", until: str = ""):
        since = since or (date.today() - timedelta(days=30)).isoformat()
        rows = ledger.list_receipts(since=since, until=until, limit=200)
        width = max(40, int(config.RECEIPT_WIDTH))
        lines = [f"EXPENSE REPORT  {since} .. {until or date.today().isoformat()}",
                 "=" * width]
        for row in rows:
            label = f"{row['purchased_on']}  {row['merchant']}"[: width - 12]
            lines.append(f"{label}{' ' * max(1, width - len(label) - 10)}"
                         f"{row['total']:>9,.2f}")
        lines += ["=" * width,
                  f"{'TOTAL':<{width - 10}}{sum(r['total'] for r in rows):>9,.2f}"]
        text = "\n".join(lines)
        result = await print_slip(text, title="expense report")
        return {"rows": len(rows), "report": text, "printed": result}

    @tool(
        "Delete a recorded expense.",
        receipt_id={"type": "integer", "description": "Receipt id"},
    )
    async def delete_expense(self, receipt_id: int):
        return {"deleted": ledger.delete_receipt(int(receipt_id)), "receipt_id": receipt_id}
