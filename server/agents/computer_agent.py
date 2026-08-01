"""Computer Agent — monitors and controls the machine the server runs on."""
from __future__ import annotations

import asyncio
import platform
import shutil
import webbrowser
from datetime import datetime

import psutil

from .. import config
from .base import BaseAgent, tool


class ComputerAgent(BaseAgent):
    name = "computer"
    description = "Controls and monitors this computer: CPU/RAM/disk stats, processes, volume, opening apps and websites, and (if enabled) shell commands."

    @tool("Get live system stats: CPU, memory, disk, battery, uptime, network.")
    async def system_stats(self):
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        stats = {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "cpu_cores": psutil.cpu_count(),
            "memory": {"used_gb": round(vm.used / 1e9, 1), "total_gb": round(vm.total / 1e9, 1), "percent": vm.percent},
            "disk": {"used_gb": round(du.used / 1e9, 1), "total_gb": round(du.total / 1e9, 1), "percent": du.percent},
            "uptime": str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).split(".")[0],
        }
        batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if batt:
            stats["battery"] = {"percent": batt.percent, "plugged_in": batt.power_plugged}
        return stats

    @tool(
        "List the top processes by CPU or memory usage.",
        sort_by={"type": "string", "description": "'cpu' or 'memory'", "required": False},
    )
    async def top_processes(self, sort_by: str = "cpu"):
        key = "memory_percent" if sort_by == "memory" else "cpu_percent"
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda p: p.get(key) or 0, reverse=True)
        return [
            {"pid": p["pid"], "name": p["name"],
             "cpu": round(p.get("cpu_percent") or 0, 1),
             "mem": round(p.get("memory_percent") or 0, 1)}
            for p in procs[:10]
        ]

    @tool(
        "Open a URL or website in the default browser on this computer.",
        url={"type": "string", "description": "Full URL, e.g. https://youtube.com"},
    )
    async def open_url(self, url: str):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        ok = webbrowser.open(url)
        return {"ok": ok, "url": url}

    @tool(
        "Launch an application by name (must be on PATH).",
        app={"type": "string", "description": "Executable name, e.g. firefox, code, vlc"},
    )
    async def open_app(self, app: str):
        path = shutil.which(app)
        if not path:
            return {"error": f"app {app!r} not found on PATH"}
        await asyncio.create_subprocess_exec(
            path, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        return {"ok": True, "launched": path}

    @tool(
        "Set the system output volume (0-100). Linux (amixer/pactl) and macOS supported.",
        percent={"type": "integer", "description": "Volume percent 0-100"},
    )
    async def set_volume(self, percent: int):
        percent = max(0, min(100, int(percent)))
        if platform.system() == "Darwin":
            cmd = ["osascript", "-e", f"set volume output volume {percent}"]
        elif shutil.which("pactl"):
            cmd = ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"]
        elif shutil.which("amixer"):
            cmd = ["amixer", "-q", "sset", "Master", f"{percent}%"]
        else:
            return {"error": "no supported volume tool found"}
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
        return {"ok": proc.returncode == 0, "volume": percent}

    @tool(
        "Run a shell command on this computer and return its output. "
        "Only available when ALLOW_SHELL=true in .env.",
        command={"type": "string", "description": "Shell command to execute"},
    )
    async def run_command(self, command: str):
        if not config.ALLOW_SHELL:
            return {"error": "shell access disabled — set ALLOW_SHELL=true in .env to enable"}
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": "command timed out after 30s"}
        return {
            "exit_code": proc.returncode,
            "stdout": out.decode(errors="replace")[-4000:],
            "stderr": err.decode(errors="replace")[-2000:],
        }
