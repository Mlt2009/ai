"""Creative Agent — manages Artist's library of J.A.R.V.I.S.-inspired prompts.

Provides tools to retrieve, search, and list the 50 curated visual / video
generation prompts stored in ``artist.prompts_data``.
"""
from __future__ import annotations

from server.agents.base import BaseAgent, tool
from artist.prompts_data import PROMPTS, THEMES


class CreativeAgent(BaseAgent):
    name = "creative"
    description = (
        "Manages a curated library of 50 J.A.R.V.I.S.-inspired creative image "
        "and video generation prompts. Can retrieve a specific prompt by number, "
        "search prompts by keyword or theme, or list available themes."
    )

    # ── Tools ──────────────────────────────────────────────────────

    @tool(
        "Retrieve a specific creative prompt by its number (1–50).",
        number={"type": "integer", "description": "Prompt number between 1 and 50"},
    )
    async def get_prompt(self, number: int) -> dict:
        if not 1 <= number <= 50:
            return {"error": f"Prompt number must be between 1 and 50, got {number}."}
        entry = next((p for p in PROMPTS if p["id"] == number), None)
        if entry is None:
            return {"error": f"Prompt #{number} not found."}
        return entry

    @tool(
        "Search prompts by a keyword (matched against title, theme, and prompt text) "
        "and/or by theme tag.",
        keyword={"type": "string",
                 "description": "Word or phrase to search for",
                 "required": False},
        theme={"type": "string",
               "description": "Theme tag to filter by (e.g. cybersecurity, coding, physics)",
               "required": False},
    )
    async def search_prompts(self, keyword: str = "", theme: str = "") -> dict:
        results = list(PROMPTS)
        if theme:
            results = [p for p in results if p["theme"].lower() == theme.lower()]
        if keyword:
            kw = keyword.lower()
            results = [
                p for p in results
                if kw in p["title"].lower()
                or kw in p["theme"].lower()
                or kw in p["prompt"].lower()
            ]
        if not results:
            return {"matches": 0, "prompts": []}
        return {
            "matches": len(results),
            "prompts": [
                {"id": p["id"], "title": p["title"], "theme": p["theme"]}
                for p in results
            ],
        }

    @tool("List all available theme tags in the prompt library.")
    async def list_themes(self) -> dict:
        return {"themes": THEMES, "total_prompts": len(PROMPTS)}
