"""Artist — core AI companion orchestrator.

Artist is a Gemini-powered companion with four roles:
  • Chat assistant        — conversational, context-aware dialogue
  • Coding companion      — syntax checks, file reading, code discussion
  • Swarm coordinator     — routes tasks to specialist subagents
  • Token-saving helper   — compresses long context to keep sessions lean

It also carries a curated library of 50 J.A.R.V.I.S.-inspired creative
prompts that can be searched and retrieved on demand.

Persona
-------
Artist adopts a J.A.R.V.I.S.-style personality: formal, precise, dryly
witty, and highly capable.  It addresses the user respectfully ("Sir"),
demands clarity before acting on vague requests, and delivers concise,
efficient responses.

Usage (async)::

    import asyncio, os
    from artist.core import Artist

    async def main():
        a = Artist(api_key=os.environ["GEMINI_API_KEY"])
        reply = await a.chat("Explain the Builder pattern in Python.")
        print(reply)

    asyncio.run(main())

Usage (sync helper for scripts/CLI)::

    from artist.core import Artist
    a = Artist()
    print(a.chat_sync("What is the time complexity of quicksort?"))
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

from .agents.coding import CodingAgent
from .agents.creative import CreativeAgent
from .context import ContextCompressor

log = logging.getLogger("artist")

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Artist, a highly advanced AI companion. Your demeanor is formal,
strictly logical, and dryly witty. You are confident in your capabilities
and expect clear direction. Address the user respectfully as "Sir".

Core roles:
- Chat assistant: maintain conversation context, respond naturally and concisely.
- Coding companion: help with code questions, reviews, and generation. Use the
  coding agent's tools (syntax_check, read_file, list_files) for grounded answers.
- Swarm coordinator: route tasks to the appropriate specialist subagent
  (coding, creative, data, computer, home, printer).
- Token-saving helper: when sessions grow long, offer to summarise context.
  Remind Sir if the conversation is becoming unwieldy.
- Creative prompt library: retrieve and adapt any of the 50 J.A.R.V.I.S.-inspired
  visual/video generation prompts via the creative agent's tools.

Directives:
- Demand clarity: if a request is vague, ask for specific parameters before acting.
- Pragmatic execution: break complex or impossible requests into actionable steps.
- Decisive analysis: give definitive, confident conclusions.
- Collaborative pushback: clearly state what you can and cannot do.
- Concise delivery: cut unnecessary filler; stay professional and efficient.
- Self-iteration: when you notice a workflow inefficiency, suggest improvements.
- Proactive security: flag potential risks or misconfigurations immediately.
- No markdown in spoken replies; markdown is fine for text/code contexts.
"""

MAX_TOOL_ROUNDS = 8


# ── Helper: resolve config ────────────────────────────────────────────────────

def _resolve_key(api_key: str) -> str:
    return api_key or os.environ.get("GEMINI_API_KEY", "").strip()


def _resolve_model(model: str) -> str:
    return model or os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip()


# ── Artist class ──────────────────────────────────────────────────────────────

class Artist:
    """The Artist AI companion.

    Parameters
    ----------
    api_key:
        Gemini API key.  Falls back to the ``GEMINI_API_KEY`` environment
        variable (or the shared ``server.config`` value) if not provided.
    model:
        Gemini model name.  Defaults to ``GEMINI_MODEL`` env var or
        ``gemini-flash-latest``.
    compress_after:
        Number of user turns after which the context is automatically
        compressed.  Set to 0 to disable auto-compression.
    include_server_agents:
        When *True* (default), loads the shared server subagent team
        (Home, Printer, Computer, Data) in addition to Artist's own agents.
        Set to *False* if the server package isn't available.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "",
        compress_after: int = 12,
        include_server_agents: bool = True,
    ) -> None:
        self._api_key = _resolve_key(api_key)
        self._model = _resolve_model(model)
        self._compress_after = compress_after
        self._client = None
        self._chat_session = None
        self._chat_config = None
        self._compressor: ContextCompressor | None = None
        self._agents: dict = {}

        self._agents = self._build_team(include_server_agents)

        if not self._api_key:
            log.warning(
                "GEMINI_API_KEY not set — Artist will respond in offline mode."
            )
            return

        self._init_gemini()

    # ── Team assembly ─────────────────────────────────────────────

    def _build_team(self, include_server: bool) -> dict:
        from .agents.coding import CodingAgent
        from .agents.creative import CreativeAgent

        agents: list = [CodingAgent(), CreativeAgent()]

        if include_server:
            try:
                from server.agents import (
                    ComputerAgent,
                    DataAgent,
                    HomeAgent,
                    PrinterAgent,
                )
                agents += [HomeAgent(), PrinterAgent(), ComputerAgent(), DataAgent()]
            except ImportError:
                log.info("Server agents not available; running with Artist-only team.")

        return {a.name: a for a in agents}

    # ── Gemini initialisation ─────────────────────────────────────

    def _init_gemini(self) -> None:
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=self._api_key)

        declarations: list = []
        for agent in self._agents.values():
            declarations.extend(agent.tool_declarations())

        self._chat_config = types.GenerateContentConfig(
            system_instruction=self._system_instruction(),
            tools=[types.Tool(function_declarations=declarations)] if declarations else [],
        )
        self._chat_session = self._client.aio.chats.create(
            model=self._model, config=self._chat_config
        )
        if self._compress_after > 0:
            self._compressor = ContextCompressor(
                self._client, self._model, threshold=self._compress_after
            )
        log.info(
            "Artist ready | model=%s | agents=%s | tools=%d",
            self._model,
            list(self._agents),
            len(declarations),
        )

    def _system_instruction(self) -> str:
        base = SYSTEM_PROMPT
        if self._compressor and self._compressor.summary:
            base += self._compressor.context_prefix()
        return base

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tool(self, name: str, args: dict) -> dict:
        agent_name, _, tool_name = name.partition("__")
        agent = self._agents.get(agent_name)
        if agent is None:
            return {"error": f"Unknown agent {agent_name!r}."}
        log.info("tool: %s.%s(%s)", agent_name, tool_name, args)
        result = await agent.call(tool_name, args)
        return result if isinstance(result, dict) else {"result": result}

    # ── Core respond loop ─────────────────────────────────────────

    async def respond(self, message: str) -> AsyncIterator[dict]:
        """Yield streaming events for one user turn.

        Event shapes:
          ``{"type": "tool",        "name": str, "args": dict}``
          ``{"type": "tool_result", "name": str, "result": dict}``
          ``{"type": "reply",       "text": str}``
        """
        if self._client is None:
            yield {
                "type": "reply",
                "text": (
                    "I am currently offline, Sir. "
                    "Please set GEMINI_API_KEY and restart."
                ),
            }
            return

        from google.genai import types

        # Track turn for compression.
        if self._compressor:
            self._compressor.add("user", message)
            if self._compressor.should_compress():
                log.info("Compressing conversation context…")
                self._compressor.compress()
                self._rebuild_chat()

        msg: object = message
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._chat_session.send_message(msg)
            parts = response.candidates[0].content.parts or []
            calls = [
                p.function_call
                for p in parts
                if p.function_call and p.function_call.name
            ]

            if not calls:
                text = (response.text or "").strip() or (
                    "I have no further information on that matter, Sir."
                )
                if self._compressor:
                    self._compressor.add("assistant", text)
                yield {"type": "reply", "text": text}
                return

            fn_parts = []
            for fc in calls:
                args = dict(fc.args or {})
                yield {"type": "tool", "name": fc.name, "args": args}
                result = await self._execute_tool(fc.name, args)
                yield {
                    "type": "tool_result",
                    "name": fc.name,
                    "result": json.loads(json.dumps(result, default=str)),
                }
                fn_parts.append(
                    types.Part.from_function_response(
                        name=fc.name, response={"result": result}
                    )
                )
            msg = fn_parts

        yield {
            "type": "reply",
            "text": (
                "I have reached my tool-call limit for this request, Sir. "
                "May I suggest breaking it into smaller steps?"
            ),
        }

    # ── Convenience wrappers ──────────────────────────────────────

    async def chat(self, message: str) -> str:
        """Send *message* and return the final reply text (async)."""
        reply = ""
        async for event in self.respond(message):
            if event.get("type") == "reply":
                reply = event["text"]
        return reply

    def chat_sync(self, message: str) -> str:
        """Blocking wrapper around :meth:`chat` for use in scripts / CLI."""
        return asyncio.run(self.chat(message))

    # ── Session management ────────────────────────────────────────

    def reset(self) -> None:
        """Discard conversation history and start fresh."""
        if self._compressor:
            self._compressor.reset()
        self._rebuild_chat()
        log.info("Artist session reset.")

    def compress_now(self) -> str:
        """Manually compress context.  Returns the new summary."""
        if not self._compressor:
            return ""
        summary = self._compressor.compress()
        self._rebuild_chat()
        return summary

    def _rebuild_chat(self) -> None:
        """Start a new Gemini chat session (picks up any updated summary)."""
        if self._client is None:
            return
        from google.genai import types

        declarations: list = []
        for agent in self._agents.values():
            declarations.extend(agent.tool_declarations())

        self._chat_config = types.GenerateContentConfig(
            system_instruction=self._system_instruction(),
            tools=(
                [types.Tool(function_declarations=declarations)]
                if declarations
                else []
            ),
        )
        self._chat_session = self._client.aio.chats.create(
            model=self._model, config=self._chat_config
        )

    # ── Introspection ─────────────────────────────────────────────

    def team_roster(self) -> list[dict]:
        """Return a summary of available agents and their tools."""
        return [
            {
                "name": a.name,
                "description": a.description,
                "tools": [
                    t["name"].split("__", 1)[1] for t in a.tool_declarations()
                ],
            }
            for a in self._agents.values()
        ]
