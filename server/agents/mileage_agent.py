"""Mileage Agent — the trip log that turns into a deduction at tax time.

The per-mile rate is *not* hardcoded: rates change every year and quoting a
stale one would put a wrong number on a tax return. Set MILEAGE_RATE to the
rate published for your tax year and jurisdiction.
"""
from __future__ import annotations

from datetime import date

from .. import config, ledger, receipt_layout
from .base import BaseAgent, tool
from .scan_agent import print_slip


class MileageAgent(BaseAgent):
    name = "mileage"
    description = ("Logs business driving: record trips with miles and purpose, "
                   "total the deduction for a period or tax year, and print or "
                   "export the log.")

    @tool(
        "Log a business trip.",
        miles={"type": "number", "description": "Miles driven"},
        purpose={"type": "string", "description": "Why — e.g. 'service call, Acme'"},
        driven_on={"type": "string", "description": "ISO date; defaults to today",
                   "required": False},
        start_place={"type": "string", "description": "Where from", "required": False},
        end_place={"type": "string", "description": "Where to", "required": False},
        round_trip={"type": "boolean", "description": "Double the miles",
                    "required": False},
        rate={"type": "number",
              "description": "Per-mile rate; defaults to the configured MILEAGE_RATE",
              "required": False},
        vehicle={"type": "string", "description": "Which vehicle", "required": False},
    )
    async def log_trip(self, miles: float, purpose: str = "", driven_on: str = "",
                       start_place: str = "", end_place: str = "",
                       round_trip: bool = False, rate: float = 0, vehicle: str = ""):
        distance = float(miles) * (2 if round_trip else 1)
        applied = float(rate) if rate else config.MILEAGE_RATE
        if not applied:
            return {"error": "no per-mile rate configured — set MILEAGE_RATE in "
                             "Settings to the rate published for your tax year"}
        trip = ledger.add_trip(distance, purpose=purpose, driven_on=driven_on,
                               start_at=start_place, end_at=end_place, rate=applied,
                               vehicle=vehicle)
        return {"trip_id": trip["id"], "date": trip["driven_on"], "miles": trip["miles"],
                "rate": trip["rate"], "deduction": trip["deduction"],
                "purpose": trip["purpose"]}

    @tool(
        "List logged trips, newest first.",
        since={"type": "string", "description": "ISO date lower bound", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
        limit={"type": "integer", "description": "Max rows (default 20)", "required": False},
    )
    async def list_trips(self, since: str = "", until: str = "", limit: int = 20):
        rows = ledger.list_trips(since=since, until=until, limit=limit)
        return {"count": len(rows),
                "trips": [{"id": r["id"], "date": r["driven_on"], "miles": r["miles"],
                           "purpose": r["purpose"], "deduction": r["deduction"]}
                          for r in rows]}

    @tool(
        "Total miles and deduction for a period.",
        since={"type": "string", "description": "ISO date lower bound; defaults to "
                                                "the start of this year", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
    )
    async def summary(self, since: str = "", until: str = ""):
        since = since or f"{date.today().year}-01-01"
        totals = ledger.mileage_totals(since=since, until=until)
        return {"since": since, "until": until or "today", "rate": config.MILEAGE_RATE,
                **totals}

    @tool(
        "Deduction total for a whole tax year.",
        year={"type": "integer", "description": "Four-digit year; defaults to this year",
              "required": False},
    )
    async def tax_year(self, year: int = 0):
        year = int(year or date.today().year)
        totals = ledger.mileage_totals(since=f"{year}-01-01", until=f"{year}-12-31")
        return {"year": year, **totals,
                "note": "verify the per-mile rate for this tax year before filing"}

    @tool(
        "Delete a logged trip.",
        trip_id={"type": "integer", "description": "Trip id from list_trips"},
    )
    async def delete_trip(self, trip_id: int):
        return {"deleted": ledger.delete_trip(int(trip_id)), "trip_id": trip_id}

    @tool(
        "Print the mileage log for a period on the paper printer.",
        since={"type": "string", "description": "ISO date lower bound; defaults to "
                                                "the start of this year", "required": False},
        until={"type": "string", "description": "ISO date upper bound", "required": False},
    )
    async def print_log(self, since: str = "", until: str = ""):
        since = since or f"{date.today().year}-01-01"
        rows = ledger.list_trips(since=since, until=until, limit=1000)
        if not rows:
            return {"error": "no trips logged in that period"}
        width = max(40, int(config.RECEIPT_WIDTH))
        lines = ["MILEAGE LOG".center(width),
                 f"{since} .. {until or date.today().isoformat()}".center(width),
                 "=" * width]
        for row in rows:
            label = f"{row['driven_on']}  {row['purpose']}"[: width - 12]
            lines.append(f"{label}{' ' * max(1, width - len(label) - 11)}"
                         f"{row['miles']:>7.1f}mi")
        totals = ledger.mileage_totals(since=since, until=until)
        lines += ["=" * width,
                  receipt_layout._row("TOTAL MILES", f"{totals['miles']:,.1f}", width),
                  receipt_layout._row("DEDUCTION", f"${totals['deduction']:,.2f}", width)]
        text = "\n".join(lines)
        return {"trips": len(rows), "log": text, **totals,
                "printed": await print_slip(text, title="mileage log")}
