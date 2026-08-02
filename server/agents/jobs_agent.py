"""Jobs Agent — the working calendar: what's booked, what's next, what's today.

Deliberately a local schedule rather than a Google/Outlook sync: it needs no
account, works offline, and exports standard .ics so a booked job can be
dropped into whatever calendar you already use.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import config, ledger
from .base import BaseAgent, tool
from .scan_agent import print_slip

STATUSES = ("scheduled", "done", "cancelled")


def parse_when(when: str) -> str:
    """Accept 'today 2pm', 'tomorrow 09:00' or an ISO timestamp.

    Returns an ISO string so it sorts correctly in SQLite; raises on nonsense
    rather than silently booking a job at the wrong time.
    """
    text = str(when).strip().lower()
    if not text:
        raise ValueError("no time given")

    day = date.today()
    for word, offset in (("today", 0), ("tomorrow", 1), ("tmrw", 1)):
        if text.startswith(word):
            day, text = day + timedelta(days=offset), text[len(word):].strip()
            break

    if not text:                       # a bare day means 8am
        return f"{day.isoformat()}T08:00"

    for fmt in ("%Y-%m-%dt%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dt%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    if len(text) == 10:                # a bare ISO date
        return f"{text}T08:00"

    clock = text.replace(" ", "")
    for fmt in ("%I%p", "%I:%M%p", "%H:%M"):
        try:
            moment = datetime.strptime(clock, fmt).time()
            return f"{day.isoformat()}T{moment.strftime('%H:%M')}"
        except ValueError:
            continue
    raise ValueError(f"couldn't read {when!r} as a date and time")


def _ics_stamp(iso: str) -> str:
    """ISO local time -> the floating local form iCalendar accepts."""
    return iso.replace("-", "").replace(":", "").ljust(15, "0")[:15]


class JobsAgent(BaseAgent):
    name = "jobs"
    description = ("The working calendar: schedule jobs and appointments, see what's "
                   "on today or this week, reschedule, mark done, and export to a "
                   ".ics calendar file.")

    @tool(
        "Put a job on the calendar.",
        title={"type": "string", "description": "What the job is"},
        when={"type": "string",
              "description": "'today 2pm', 'tomorrow 09:00' or '2026-08-05T14:00'"},
        customer={"type": "string", "description": "Who it's for", "required": False},
        location={"type": "string", "description": "Where", "required": False},
        hours={"type": "number", "description": "How long, in hours", "required": False},
        note={"type": "string", "description": "Anything else", "required": False},
    )
    async def schedule(self, title: str, when: str, customer: str = "",
                       location: str = "", hours: float = 0, note: str = ""):
        try:
            starts = parse_when(when)
        except ValueError as exc:
            return {"error": str(exc)}
        ends = ""
        if hours:
            ends = (datetime.fromisoformat(starts)
                    + timedelta(hours=float(hours))).strftime("%Y-%m-%dT%H:%M")
        job = ledger.add_job(title, starts, customer=customer, ends_at=ends,
                             location=location, note=note)
        return {"job_id": job["id"], "title": job["title"], "starts_at": job["starts_at"],
                "ends_at": job["ends_at"], "customer": job["customer"],
                "location": job["location"]}

    @tool(
        "What's on the calendar.",
        window={"type": "string",
                "description": "'today', 'tomorrow', 'week', 'all' (default 'week')",
                "required": False},
        include_done={"type": "boolean", "description": "Include finished jobs",
                      "required": False},
    )
    async def agenda(self, window: str = "week", include_done: bool = False):
        today = date.today()
        window = (window or "week").lower()
        if window == "today":
            since, until = today.isoformat(), f"{today.isoformat()}T23:59"
        elif window == "tomorrow":
            day = (today + timedelta(days=1)).isoformat()
            since, until = day, f"{day}T23:59"
        elif window == "all":
            since = until = ""
        else:
            since = today.isoformat()
            until = f"{(today + timedelta(days=7)).isoformat()}T23:59"
        rows = ledger.list_jobs(since=since, until=until,
                                status="" if include_done else "scheduled")
        return {"window": window, "count": len(rows),
                "jobs": [{"id": r["id"], "title": r["title"], "starts_at": r["starts_at"],
                          "customer": r["customer"], "location": r["location"],
                          "status": r["status"]} for r in rows]}

    @tool("The next job coming up.")
    async def next_job(self):
        rows = ledger.list_jobs(since=datetime.now().strftime("%Y-%m-%dT%H:%M"),
                                status="scheduled", limit=1)
        if not rows:
            return {"next": None, "message": "nothing scheduled"}
        job = rows[0]
        starts = datetime.fromisoformat(job["starts_at"])
        away = starts - datetime.now()
        hours = round(away.total_seconds() / 3600, 1)
        return {"next": {"id": job["id"], "title": job["title"],
                         "starts_at": job["starts_at"], "customer": job["customer"],
                         "location": job["location"]},
                "hours_away": hours}

    @tool(
        "Move a job to a new time.",
        job_id={"type": "integer", "description": "Job id from the agenda"},
        when={"type": "string", "description": "New time, same formats as scheduling"},
    )
    async def reschedule(self, job_id: int, when: str):
        try:
            starts = parse_when(when)
        except ValueError as exc:
            return {"error": str(exc)}
        job = ledger.update_job(int(job_id), starts_at=starts)
        return {"error": f"no job #{job_id}"} if not job else \
               {"job_id": job["id"], "title": job["title"], "starts_at": job["starts_at"]}

    @tool(
        "Mark a job done or cancelled.",
        job_id={"type": "integer", "description": "Job id from the agenda"},
        status={"type": "string", "description": "'done' or 'cancelled'"},
    )
    async def set_status(self, job_id: int, status: str):
        status = str(status).strip().lower()
        if status not in STATUSES:
            return {"error": f"status must be one of {', '.join(STATUSES)}"}
        job = ledger.update_job(int(job_id), status=status)
        return {"error": f"no job #{job_id}"} if not job else \
               {"job_id": job["id"], "title": job["title"], "status": job["status"]}

    @tool(
        "Export the schedule as a .ics calendar file you can import anywhere.",
        window={"type": "string", "description": "'week', 'all' (default 'all')",
                "required": False},
    )
    async def export_calendar(self, window: str = "all"):
        since = date.today().isoformat() if window == "week" else ""
        until = (f"{(date.today() + timedelta(days=7)).isoformat()}T23:59"
                 if window == "week" else "")
        rows = ledger.list_jobs(since=since, until=until, limit=500)
        if not rows:
            return {"error": "nothing on the calendar to export"}

        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Atlas//Jobs//EN"]
        for job in rows:
            ends = job["ends_at"] or (
                datetime.fromisoformat(job["starts_at"]) + timedelta(hours=1)
            ).strftime("%Y-%m-%dT%H:%M")
            summary = job["title"] + (f" — {job['customer']}" if job["customer"] else "")
            lines += ["BEGIN:VEVENT", f"UID:atlas-job-{job['id']}@localhost",
                      f"DTSTART:{_ics_stamp(job['starts_at'])}",
                      f"DTEND:{_ics_stamp(ends)}",
                      f"SUMMARY:{summary}",
                      f"LOCATION:{job['location']}",
                      f"DESCRIPTION:{job['note']}", "END:VEVENT"]
        lines.append("END:VCALENDAR")

        out_dir = Path(config.DATA_DIR) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "schedule.ics"
        await asyncio.to_thread(target.write_text, "\r\n".join(lines), encoding="utf-8")
        return {"ics": str(target), "events": len(rows)}

    @tool("Print today's job sheet to take with you.")
    async def print_day_sheet(self):
        today = date.today().isoformat()
        rows = ledger.list_jobs(since=today, until=f"{today}T23:59", status="scheduled")
        if not rows:
            return {"error": "nothing scheduled today"}
        width = max(32, int(config.RECEIPT_WIDTH))
        lines = ["JOBS TODAY".center(width), today.center(width), "=" * width]
        for job in rows:
            clock = job["starts_at"].split("T")[-1]
            lines.append(f"{clock}  {job['title']}"[:width])
            if job["customer"]:
                lines.append(f"      {job['customer']}"[:width])
            if job["location"]:
                lines.append(f"      {job['location']}"[:width])
            lines.append("-" * width)
        text = "\n".join(lines)
        return {"jobs": len(rows), "sheet": text,
                "printed": await print_slip(text, title="job sheet")}
