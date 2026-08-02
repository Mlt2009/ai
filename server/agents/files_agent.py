"""Files Agent — real control over the files on this computer (Windows too).

Browse, search, read, write, move, copy, delete, zip and open anything on the
machine the server runs on. Reads are allowed inside FILE_ROOTS (your home
folder by default, or `*` for the whole drive); anything that *changes* the
disk additionally requires ALLOW_FILE_WRITE, because this server is reachable
from your phone and a stolen link should not be able to delete your documents.
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path

from .. import config
from .base import BaseAgent, tool

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".css",
                 ".js", ".ts", ".py", ".sh", ".bat", ".ps1", ".ini", ".cfg", ".log", ".sql",
                 ".toml", ".env", ".c", ".h", ".cpp", ".cs", ".java", ".go", ".rs", ".rb"}


def roots() -> list[Path]:
    """The directories this agent may touch. `*` means the entire filesystem."""
    raw = (config.FILE_ROOTS or "").strip()
    if raw == "*":
        return []
    entries = [r.strip() for r in raw.split(os.pathsep) if r.strip()] or [str(Path.home())]
    return [Path(os.path.expandvars(e)).expanduser().resolve() for e in entries]


def resolve(path: str) -> Path:
    """Expand `~`, `%USERPROFILE%`/`$HOME`, and confirm the path is in bounds."""
    if not str(path).strip():
        raise ValueError("no path given")
    target = Path(os.path.expandvars(str(path))).expanduser()
    if not target.is_absolute():
        target = (Path.home() / target)
    target = target.resolve()
    allowed = roots()
    if allowed and not any(target == r or r in target.parents for r in allowed):
        raise PermissionError(
            f"{target} is outside the allowed folders ({', '.join(map(str, allowed))}). "
            "Widen FILE_ROOTS in Settings to reach it.")
    return target


def require_write() -> None:
    if not config.ALLOW_FILE_WRITE:
        raise PermissionError(
            "changing files is switched off — turn on 'Allow file changes' in Settings "
            "to let me write, move or delete on this computer")


def describe(path: Path) -> dict:
    try:
        stat = path.stat()
    except OSError:
        return {"name": path.name, "path": str(path), "type": "unreadable"}
    return {
        "name": path.name,
        "path": str(path),
        "type": "folder" if path.is_dir() else "file",
        "kb": None if path.is_dir() else round(stat.st_size / 1024, 1),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="minutes"),
    }


class FilesAgent(BaseAgent):
    name = "files"
    description = ("Full control of the files on this computer (Windows, macOS or Linux): "
                   "browse folders, search by name or content, read and write files, "
                   "move, copy, rename, delete, zip, and open anything in its app.")

    # ── reading ───────────────────────────────────────────────────

    @tool(
        "List what's inside a folder.",
        path={"type": "string",
              "description": r"Folder path, e.g. C:\Users\me\Documents or ~/Desktop"},
        pattern={"type": "string", "description": "Glob filter such as *.pdf",
                 "required": False},
    )
    async def list_folder(self, path: str, pattern: str = "*"):
        folder = resolve(path)
        if not folder.is_dir():
            return {"error": f"{folder} is not a folder"}
        entries = sorted(folder.glob(pattern or "*"),
                         key=lambda p: (p.is_file(), p.name.lower()))
        return {"folder": str(folder), "count": len(entries),
                "entries": [describe(p) for p in entries[:200]]}

    @tool("List the usual places: home, Desktop, Documents, Downloads, Pictures.")
    async def known_folders(self):
        home = Path.home()
        found = {}
        for label in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"):
            candidate = home / label
            if candidate.is_dir():
                found[label.lower()] = str(candidate)
        return {"home": str(home), "folders": found,
                "os": f"{platform.system()} {platform.release()}"}

    @tool(
        "Read a text file's contents.",
        path={"type": "string", "description": "Full path to the file"},
        max_kb={"type": "integer", "description": "Stop after this many KB (default 64)",
                "required": False},
    )
    async def read_file(self, path: str, max_kb: int = 64):
        target = resolve(path)
        if not target.is_file():
            return {"error": f"{target} is not a file"}
        limit = max(1, min(int(max_kb or 64), 1024)) * 1024
        data = await asyncio.to_thread(target.read_bytes)
        truncated = len(data) > limit
        text = data[:limit].decode("utf-8", errors="replace")
        return {"path": str(target), "truncated": truncated, "text": text}

    @tool(
        "Search for files by name, and optionally by the text inside them.",
        root={"type": "string", "description": "Folder to search under"},
        pattern={"type": "string", "description": "Name glob, e.g. *.xlsx or invoice*"},
        contains={"type": "string", "description": "Only files containing this text",
                  "required": False},
        limit={"type": "integer", "description": "Max results (default 40)",
               "required": False},
    )
    async def search_files(self, root: str, pattern: str = "*", contains: str = "",
                           limit: int = 40):
        base = resolve(root)
        limit = max(1, min(int(limit or 40), 200))

        def scan() -> list[dict]:
            hits = []
            for candidate in base.rglob(pattern or "*"):
                if not candidate.is_file():
                    continue
                if contains:
                    if candidate.suffix.lower() not in TEXT_SUFFIXES:
                        continue
                    try:
                        blob = candidate.read_bytes()[:512 * 1024]
                    except OSError:
                        continue
                    if contains.lower() not in blob.decode("utf-8", errors="ignore").lower():
                        continue
                hits.append(describe(candidate))
                if len(hits) >= limit:
                    break
            return hits

        results = await asyncio.to_thread(scan)
        return {"root": str(base), "pattern": pattern, "count": len(results),
                "matches": results}

    @tool(
        "Show free and used space on a drive.",
        path={"type": "string", "description": r"Any path on the drive, e.g. C:\ ",
              "required": False},
    )
    async def disk_space(self, path: str = ""):
        target = resolve(path) if path else Path.home()
        usage = shutil.disk_usage(target)
        return {"path": str(target),
                "total_gb": round(usage.total / 1e9, 1),
                "used_gb": round(usage.used / 1e9, 1),
                "free_gb": round(usage.free / 1e9, 1),
                "percent_used": round(usage.used / usage.total * 100, 1)}

    # ── writing (gated) ───────────────────────────────────────────

    @tool(
        "Create or overwrite a text file.",
        path={"type": "string", "description": "Full path to write"},
        content={"type": "string", "description": "The file's new contents"},
        append={"type": "boolean", "description": "Append instead of overwrite",
                "required": False},
    )
    async def write_file(self, path: str, content: str, append: bool = False):
        require_write()
        target = resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            lambda: target.open("a" if append else "w", encoding="utf-8").write(content))
        return {"path": str(target), "bytes": len(content.encode()),
                "mode": "appended" if append else "written"}

    @tool(
        "Create a folder (including any missing parents).",
        path={"type": "string", "description": "Folder path to create"},
    )
    async def make_folder(self, path: str):
        require_write()
        target = resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        return {"created": str(target)}

    @tool(
        "Move or rename a file or folder.",
        source={"type": "string", "description": "What to move"},
        destination={"type": "string", "description": "Where it should end up"},
    )
    async def move(self, source: str, destination: str):
        require_write()
        src, dst = resolve(source), resolve(destination)
        if dst.is_dir():
            dst = dst / src.name
        await asyncio.to_thread(shutil.move, str(src), str(dst))
        return {"moved": str(src), "to": str(dst)}

    @tool(
        "Copy a file or folder.",
        source={"type": "string", "description": "What to copy"},
        destination={"type": "string", "description": "Where to copy it"},
    )
    async def copy(self, source: str, destination: str):
        require_write()
        src, dst = resolve(source), resolve(destination)
        if src.is_dir():
            await asyncio.to_thread(shutil.copytree, str(src), str(dst), dirs_exist_ok=True)
        else:
            if dst.is_dir():
                dst = dst / src.name
            await asyncio.to_thread(shutil.copy2, str(src), str(dst))
        return {"copied": str(src), "to": str(dst)}

    @tool(
        "Delete a file, or a folder and everything in it. This is permanent.",
        path={"type": "string", "description": "What to delete"},
        recursive={"type": "boolean",
                   "description": "Required to delete a folder that has contents",
                   "required": False},
    )
    async def delete(self, path: str, recursive: bool = False):
        require_write()
        target = resolve(path)
        if target in roots() or target == Path.home() or target.parent == target:
            return {"error": f"refusing to delete {target} — that's a root folder"}
        if target.is_dir():
            if not recursive and any(target.iterdir()):
                return {"error": f"{target} is not empty — call again with recursive=true "
                                 "if you really mean it"}
            await asyncio.to_thread(shutil.rmtree, str(target))
        else:
            await asyncio.to_thread(target.unlink)
        return {"deleted": str(target)}

    @tool(
        "Zip a folder or file into an archive.",
        path={"type": "string", "description": "Folder or file to compress"},
        destination={"type": "string", "description": "Output .zip path", "required": False},
    )
    async def zip_up(self, path: str, destination: str = ""):
        require_write()
        src = resolve(path)
        dst = resolve(destination) if destination else src.with_suffix(".zip")
        base = str(dst)[:-4] if str(dst).lower().endswith(".zip") else str(dst)
        archive = await asyncio.to_thread(
            shutil.make_archive, base, "zip",
            str(src if src.is_dir() else src.parent),
            None if src.is_dir() else src.name)
        return {"zipped": str(src), "archive": archive}

    @tool(
        "Open a file or folder in its normal application on this computer.",
        path={"type": "string", "description": "What to open"},
    )
    async def open_in_app(self, path: str):
        target = resolve(path)
        system = platform.system()
        if system == "Windows":
            await asyncio.to_thread(os.startfile, str(target))  # type: ignore[attr-defined]
            return {"opened": str(target)}
        opener = "open" if system == "Darwin" else "xdg-open"
        if not shutil.which(opener):
            return {"error": f"no {opener} on this machine"}
        proc = await asyncio.create_subprocess_exec(
            opener, str(target), stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0:
            return {"error": err.decode(errors="replace").strip()}
        return {"opened": str(target)}
