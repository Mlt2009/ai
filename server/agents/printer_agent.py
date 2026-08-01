"""Printer Agent — 3D printing via OctoPrint and paper printing via CUPS."""
from __future__ import annotations

import asyncio
import shutil
import tempfile

import httpx

from .. import config
from .base import BaseAgent, tool


class PrinterAgent(BaseAgent):
    name = "printer"
    description = "Controls printers: OctoPrint 3D printer (status, jobs, temperatures, pause/resume/cancel) and regular paper printing via CUPS."

    def _octo(self) -> httpx.AsyncClient:
        if not config.OCTOPRINT_API_KEY:
            raise RuntimeError("OCTOPRINT_API_KEY is not configured (.env)")
        return httpx.AsyncClient(
            base_url=f"{config.OCTOPRINT_URL}/api",
            headers={"X-Api-Key": config.OCTOPRINT_API_KEY},
            timeout=10,
        )

    # ── 3D printer (OctoPrint) ────────────────────────────────────

    @tool("Get 3D printer status: state, hotend/bed temperatures, and current job progress.")
    async def printer_status(self):
        async with self._octo() as c:
            printer, job = await asyncio.gather(c.get("/printer"), c.get("/job"))
            out: dict = {}
            if printer.status_code == 200:
                p = printer.json()
                out["state"] = p.get("state", {}).get("text")
                out["temperatures"] = p.get("temperature", {})
            if job.status_code == 200:
                j = job.json()
                out["job"] = {
                    "file": (j.get("job", {}).get("file") or {}).get("name"),
                    "progress_pct": (j.get("progress") or {}).get("completion"),
                    "time_left_s": (j.get("progress") or {}).get("printTimeLeft"),
                }
            return out or {"error": "printer unreachable"}

    @tool(
        "Control the current 3D print job.",
        action={"type": "string", "description": "One of: pause, resume, cancel, start"},
    )
    async def job_control(self, action: str):
        action = action.lower()
        if action not in {"pause", "resume", "cancel", "start"}:
            return {"error": f"invalid action {action!r}"}
        body = {"command": "pause", "action": action} if action in {"pause", "resume"} else {"command": action}
        async with self._octo() as c:
            r = await c.post("/job", json=body)
            return {"ok": r.status_code == 204, "action": action}

    @tool(
        "Set 3D printer temperatures.",
        hotend={"type": "number", "description": "Hotend target °C", "required": False},
        bed={"type": "number", "description": "Bed target °C", "required": False},
    )
    async def set_temperature(self, hotend: float | None = None, bed: float | None = None):
        results = {}
        async with self._octo() as c:
            if hotend is not None:
                r = await c.post("/printer/tool", json={"command": "target", "targets": {"tool0": hotend}})
                results["hotend"] = r.status_code == 204
            if bed is not None:
                r = await c.post("/printer/bed", json={"command": "target", "target": bed})
                results["bed"] = r.status_code == 204
        return results or {"error": "nothing to set"}

    @tool("List printable files uploaded to OctoPrint.")
    async def list_files(self):
        async with self._octo() as c:
            r = await c.get("/files")
            r.raise_for_status()
            files = [f.get("name") for f in r.json().get("files", [])]
            return {"files": files[:50]}

    @tool(
        "Select an uploaded file and start printing it.",
        filename={"type": "string", "description": "File name as shown by list_files"},
    )
    async def print_file(self, filename: str):
        async with self._octo() as c:
            r = await c.post(f"/files/local/{filename}", json={"command": "select", "print": True})
            return {"ok": r.status_code == 204, "file": filename}

    # ── Paper printer (CUPS) ──────────────────────────────────────

    @tool(
        "Print text on the regular paper printer (via CUPS lp).",
        text={"type": "string", "description": "Text content to print"},
        title={"type": "string", "description": "Job title", "required": False},
    )
    async def print_text(self, text: str, title: str = "companion"):
        if not shutil.which("lp"):
            return {"error": "CUPS 'lp' command not found on this machine"}
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text)
            path = f.name
        cmd = ["lp", "-t", title]
        if config.CUPS_PRINTER:
            cmd += ["-d", config.CUPS_PRINTER]
        cmd.append(path)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return {"error": err.decode().strip()}
        return {"ok": True, "job": out.decode().strip()}

    @tool("List paper printers and their queue status (lpstat).")
    async def paper_printer_status(self):
        if not shutil.which("lpstat"):
            return {"error": "CUPS 'lpstat' command not found"}
        proc = await asyncio.create_subprocess_exec(
            "lpstat", "-p", "-o", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        return {"status": (out.decode() or err.decode()).strip() or "no printers found"}
