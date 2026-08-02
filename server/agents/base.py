"""Base class for every subagent in the companion's team.

Each subagent exposes a set of *tools*: async methods the orchestrator can
call via Gemini function-calling. A tool is registered with the @tool
decorator, which records a JSON-schema declaration Gemini understands.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable


def tool(description: str, **params: dict):
    """Mark a subagent method as a callable tool.

    `params` maps parameter name -> {"type": ..., "description": ...,
    optionally "required": False}.
    """

    def wrap(fn: Callable):
        required = [n for n, p in params.items() if p.get("required", True)]
        properties = {
            n: {k: v for k, v in p.items() if k != "required"}
            for n, p in params.items()
        }
        fn._tool_decl = {
            "name": fn.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        return fn

    return wrap


class BaseAgent:
    """A specialist agent. Subclasses define tools with @tool."""

    name: str = "agent"
    description: str = ""

    def tool_declarations(self) -> list[dict]:
        """Plain JSON-Schema declarations, namespaced `agent__tool`.

        This is the neutral shape; the two brains convert it below, so a new
        tool is written once and both Gemini and OpenAI can call it.
        """
        decls = []
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            decl = getattr(method, "_tool_decl", None)
            if decl:
                decls.append({
                    "name": f"{self.name}__{decl['name']}",
                    "description": decl["description"],
                    "parameters": decl["parameters"],
                })
        return decls

    def gemini_declarations(self) -> list[dict]:
        """Gemini wants SCREAMING type names."""
        out = []
        for decl in self.tool_declarations():
            params = decl["parameters"]
            out.append({
                "name": decl["name"],
                "description": decl["description"],
                "parameters": {
                    "type": "OBJECT",
                    "properties": {n: {**p, "type": p["type"].upper()}
                                   for n, p in params["properties"].items()},
                    "required": params["required"],
                },
            })
        return out

    def openai_declarations(self) -> list[dict]:
        """OpenAI wraps each function in a `{"type": "function"}` envelope."""
        return [{"type": "function", "function": decl} for decl in self.tool_declarations()]

    async def call(self, tool_name: str, args: dict) -> Any:
        method = getattr(self, tool_name, None)
        if method is None or not hasattr(method, "_tool_decl"):
            return {"error": f"unknown tool {tool_name!r} on agent {self.name}"}
        try:
            return await method(**args)
        except Exception as exc:  # surface failures to the model, don't crash
            return {"error": f"{type(exc).__name__}: {exc}"}
