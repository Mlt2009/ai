"""Shopping Agent — the list, the prices, and what the run will cost you."""
from __future__ import annotations

from datetime import date

from .. import brain, config, ledger
from .base import BaseAgent, tool
from .scan_agent import print_slip


class ShoppingAgent(BaseAgent):
    name = "shopping"
    description = ("Your shopping companion: the running list (add, check off, clear), "
                   "grouping the run by store, live price and deal lookups, and what "
                   "you've already spent this month.")

    @tool(
        "Add something to the shopping list.",
        item={"type": "string", "description": "What to buy"},
        qty={"type": "string", "description": "How many/much, e.g. '2' or '1 gal'",
             "required": False},
        store={"type": "string", "description": "Which store, if it matters",
               "required": False},
        note={"type": "string", "description": "Brand, size, or other detail",
              "required": False},
    )
    async def add_to_list(self, item: str, qty: str = "1", store: str = "", note: str = ""):
        row = ledger.add_item(item, qty=qty, store=store, note=note)
        return {"added": row["name"], "qty": row["qty"], "store": row["store"],
                "open_items": len(ledger.list_items())}

    @tool(
        "Show the shopping list, grouped by store.",
        store={"type": "string", "description": "Only this store", "required": False},
        include_done={"type": "boolean", "description": "Include checked-off items",
                      "required": False},
    )
    async def show_list(self, store: str = "", include_done: bool = False):
        rows = ledger.list_items(store=store, include_done=include_done)
        grouped: dict[str, list] = {}
        for row in rows:
            key = row["store"] or "anywhere"
            grouped.setdefault(key, []).append(
                {"item": row["name"], "qty": row["qty"], "note": row["note"],
                 "done": bool(row["done"])})
        return {"count": len(rows), "by_store": grouped}

    @tool(
        "Check an item off the shopping list.",
        item={"type": "string", "description": "Item name (partial match is fine)"},
    )
    async def check_off(self, item: str):
        count = ledger.check_off(item)
        return {"checked_off": count, "remaining": len(ledger.list_items())} if count else \
               {"error": f"nothing on the list matches {item!r}"}

    @tool(
        "Clear the shopping list.",
        done_only={"type": "boolean",
                   "description": "True clears only checked-off items (default), "
                                  "False wipes the whole list", "required": False},
    )
    async def clear_list(self, done_only: bool = True):
        return {"removed": ledger.clear_items(done_only=done_only)}

    @tool("Print the shopping list on the paper printer to take with you.")
    async def print_list(self):
        rows = ledger.list_items()
        if not rows:
            return {"error": "the shopping list is empty"}
        width = max(24, int(config.RECEIPT_WIDTH))
        lines = ["SHOPPING LIST".center(width), date.today().isoformat().center(width),
                 "=" * width]
        current_store = None
        for row in rows:
            store = row["store"] or "anywhere"
            if store != current_store:
                lines += ["", f"-- {store} --"]
                current_store = store
            detail = f" ({row['note']})" if row["note"] else ""
            lines.append(f"[ ] {row['qty']} x {row['name']}{detail}"[:width])
        text = "\n".join(lines)
        return {"items": len(rows), "list": text,
                "printed": await print_slip(text, title="shopping list")}

    @tool(
        "Look up current prices, deals or where to buy something, using live web results.",
        query={"type": "string", "description": "What to price, e.g. '1/2 inch copper "
                                                "pipe at Home Depot'"},
    )
    async def price_check(self, query: str):
        try:
            answer = await brain.web_answer(
                f"Current prices and where to buy: {query}. Give the typical price "
                f"range, the cheapest retailer you can verify, and the date of the "
                f"information. Be brief and say plainly if you cannot verify a price.")
        except Exception as exc:
            # Never guess a price from memory — say we couldn't check.
            return {"query": query, "error": f"{exc}"}
        return {"query": query, "answer": answer, "grounded_by": brain.provider()}

    @tool("How much has been spent on shopping-type categories so far this month.")
    async def spend_so_far(self):
        since = date.today().replace(day=1).isoformat()
        groups = ledger.totals("category", since=since)
        return {"since": since,
                "total": round(sum(g["total"] or 0 for g in groups), 2),
                "by_category": groups,
                "budgets": ledger.budget_status()}
