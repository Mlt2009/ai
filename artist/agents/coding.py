"""Coding Agent — helps Artist with software development tasks.

Provides tools for syntax checking, file reading, and directory listing
so the underlying language model can give precise, grounded coding answers.
"""
from __future__ import annotations

import ast
from pathlib import Path

from server.agents.base import BaseAgent, tool


class CodingAgent(BaseAgent):
    name = "coding"
    description = (
        "Assists with software development: checks Python syntax, reads source "
        "files, and lists directory contents so Artist can give grounded code "
        "answers, reviews, and generation guidance."
    )

    # ── Tools ──────────────────────────────────────────────────────

    @tool(
        "Check Python source code for syntax errors.",
        code={"type": "string", "description": "The Python code to check"},
    )
    async def syntax_check(self, code: str) -> dict:
        try:
            ast.parse(code)
            return {"valid": True, "message": "No syntax errors found."}
        except SyntaxError as exc:
            return {
                "valid": False,
                "line": exc.lineno,
                "offset": exc.offset,
                "message": str(exc),
            }

    @tool(
        "Read a source file from disk so Artist can discuss or review it.",
        path={"type": "string", "description": "Absolute or relative path to the file"},
    )
    async def read_file(self, path: str) -> dict:
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            return {
                "path": path,
                "lines": len(lines),
                "content": content[:8000],  # cap to avoid huge tool responses
                "truncated": len(content) > 8000,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @tool(
        "List files and sub-directories inside a directory (non-recursive).",
        path={"type": "string",
              "description": "Directory path to list (default: current directory)",
              "required": False},
    )
    async def list_files(self, path: str = ".") -> dict:
        try:
            root = Path(path)
            entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name))
            return {
                "path": str(root.resolve()),
                "entries": [
                    {"name": e.name, "type": "file" if e.is_file() else "dir"}
                    for e in entries
                ],
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
