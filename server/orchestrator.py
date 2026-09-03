"""Mehltani — the orchestrator that runs the subagent team.

One brain (Gemini or OpenAI) sits on top; every specialist subagent registers
its tools with it. The model decides which agent/tool to call (function
calling), the orchestrator executes it, feeds the result back, and loops until
the model produces a final spoken answer.

Two things make this more than a fixed tool router:

  * the system prompt is rebuilt at the start of every new session from
    identity.py + the live style_memory profile, so a session started after a
    week of verdicts talks like it knows you, without a restart.
  * agents Mehltani writes for himself (server/agents/generated/, via
    factory.py) are loaded alongside the hand-written team. A newly created
    subagent is callable starting with the next session — reconnect, or send
    a `reset`, to pick up the new tool list in this same conversation.

Uses the modern `google-genai` SDK — the same one the A.D.A. desktop frontend
uses for the Gemini Live API, so both frontends share one team.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from . import brain, config, factory, identity, style_memory
from .agents import (ComputerAgent, CouncilAgent, DataAgent, EvolutionAgent,
                     FilesAgent, FinanceAgent, GlamAgent, GuardianAgent,
                     HomeAgent, PhotoshootAgent, PrinterAgent, ScanAgent,
                     ShoppingAgent, StyleAgent, TrendAgent, WhatsAppAgent,
                     WorkspaceAgent)
from .agents.base import BaseAgent

log = logging.getLogger("mehltani")

MAX_TOOL_ROUNDS = 8

# Calling either of these means the generated-agent set on disk just changed —
# refresh self.agents so a create-then-call inside the same turn can resolve.
_AGENT_ROSTER_TOOLS = {"evolution__create_subagent", "evolution__remove_subagent"}


def build_team() -> dict[str, BaseAgent]:
    agents: list[BaseAgent] = [
        StyleAgent(), PhotoshootAgent(), GlamAgent(), TrendAgent(), WhatsAppAgent(),
        WorkspaceAgent(), ScanAgent(), FinanceAgent(), ShoppingAgent(), CouncilAgent(),
        FilesAgent(), ComputerAgent(), PrinterAgent(), HomeAgent(), DataAgent(),
        GuardianAgent(), EvolutionAgent(),
    ]
    team = {a.name: a for a in agents}
    team.update(factory.load_all())  # subagents Mehltani wrote for himself
    return team


async def execute_tool(agents: dict[str, BaseAgent], name: str, args: dict) -> dict:
    """Route a namespaced `agent__tool` call to the right subagent."""
    agent_name, _, tool_name = name.partition("__")
    agent = agents.get(agent_name)
    if agent is None:
        return {"error": f"unknown agent {agent_name!r}"}
    log.info("tool call: %s.%s(%s)", agent_name, tool_name, args)
    result = await agent.call(tool_name, args)
    if not isinstance(result, dict):
        result = {"result": result}
    return result


class Orchestrator:
    def __init__(self) -> None:
        self.agents = build_team()
        self._client = None
        self._chat_config = None
        self._sessions: dict[str, object] = {}  # per-client chat sessions
        self.provider = brain.provider()
        if self.provider == "gemini":
            self._init_gemini()
        elif self.provider == "openai":
            self._init_openai()
        else:
            log.warning("no GEMINI_API_KEY or OPENAI_API_KEY — running in offline mode")

    def tool_count(self) -> int:
        return sum(len(a.tool_declarations()) for a in self.agents.values())

    def system_prompt(self) -> str:
        """Fresh every time it's called — the taste profile keeps moving."""
        return identity.system_prompt(style_memory.summary())

    def reload_generated_agents(self) -> None:
        """Pick up subagents Mehltani has just written for himself.

        Rebuilds tool declarations for future chat sessions. A session already
        in flight keeps the tool list it started with — the model can't call a
        tool it was never told about — but self.agents is updated immediately,
        so routing is correct the moment a new session (or `reset`) picks up
        the refreshed declarations.
        """
        hand_written = {n: a for n, a in self.agents.items()
                        if not a.__class__.__module__.startswith(
                            "server.agents.generated")}
        self.agents = {**hand_written, **factory.load_all()}
        if self.provider == "gemini" and self._client is not None:
            self._init_gemini()
        elif self.provider == "openai" and self._client is not None:
            self._init_openai()

    # ── Gemini setup ──────────────────────────────────────────────

    def _init_gemini(self) -> None:
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        declarations = []
        for agent in self.agents.values():
            declarations.extend(agent.gemini_declarations())
        self._declarations = declarations
        log.info("Gemini ready with %d tools from %d subagents",
                 len(declarations), len(self.agents))

    def _gemini_config(self):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=self.system_prompt(),
            tools=[types.Tool(function_declarations=self._declarations)],
        )

    # ── OpenAI setup ──────────────────────────────────────────────

    def _init_openai(self) -> None:
        """No SDK client to build — we own the history and post each turn."""
        self._tools = []
        for agent in self.agents.values():
            self._tools.extend(agent.openai_declarations())
        self._client = "openai"  # marks "we have a brain" for respond()
        log.info("OpenAI ready (%s) with %d tools from %d subagents",
                 config.OPENAI_MODEL, len(self._tools), len(self.agents))

    def _chat(self, session_id: str):
        chat = self._sessions.get(session_id)
        if chat is None:
            chat = self._client.aio.chats.create(
                model=config.GEMINI_MODEL, config=self._gemini_config())
            self._sessions[session_id] = chat
        return chat

    # ── Main entry: one user turn ─────────────────────────────────

    async def respond(self, session_id: str, text: str) -> AsyncIterator[dict]:
        """Yield events for one user turn: {'type': 'tool'|'tool_result'|'reply', ...}."""
        if self._client is None:
            yield {"type": "reply",
                   "text": "I'm running without a brain right now — add a Gemini "
                           "or OpenAI key in Settings and I'll wake up."}
            return
        if self.provider == "openai":
            async for event in self._respond_openai(session_id, text):
                yield event
            return

        from google.genai import types

        chat = self._chat(session_id)
        message: object = text
        for _ in range(MAX_TOOL_ROUNDS):
            response = await chat.send_message(message)
            parts = response.candidates[0].content.parts or []
            calls = [p.function_call for p in parts
                     if p.function_call and p.function_call.name]
            if not calls:
                yield {"type": "reply", "text": (response.text or "").strip()
                       or "Sorry, I came up empty on that one."}
                return
            # Execute every requested tool, stream progress to the client.
            fn_parts = []
            for fc in calls:
                args = dict(fc.args or {})
                yield {"type": "tool", "name": fc.name, "args": args}
                result = await execute_tool(self.agents, fc.name, args)
                if fc.name in _AGENT_ROSTER_TOOLS:
                    self.reload_generated_agents()
                yield {"type": "tool_result", "name": fc.name,
                       "result": json.loads(json.dumps(result, default=str))}
                fn_parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": result}))
            message = fn_parts

        yield {"type": "reply",
               "text": "I hit my tool-call limit on that one — try breaking the request into smaller steps."}

    # ── OpenAI turn ───────────────────────────────────────────────

    async def _respond_openai(self, session_id: str, text: str) -> AsyncIterator[dict]:
        """Same loop, OpenAI's wire format. We keep the history ourselves."""
        history = self._sessions.get(session_id)
        if not isinstance(history, list):
            history = [{"role": "system", "content": self.system_prompt()}]
            self._sessions[session_id] = history
        history.append({"role": "user", "content": text})

        for _ in range(MAX_TOOL_ROUNDS):
            message = await brain.openai_chat(history, self._tools)
            calls = brain.parse_tool_calls(message)
            # The assistant turn must go back verbatim, tool_calls included.
            history.append({"role": "assistant",
                            "content": message.get("content") or "",
                            **({"tool_calls": message["tool_calls"]}
                               if message.get("tool_calls") else {})})
            if not calls:
                yield {"type": "reply", "text": (message.get("content") or "").strip()
                       or "Sorry, I came up empty on that one."}
                return
            for call in calls:
                yield {"type": "tool", "name": call["name"], "args": call["args"]}
                result = await execute_tool(self.agents, call["name"], call["args"])
                if call["name"] in _AGENT_ROSTER_TOOLS:
                    self.reload_generated_agents()
                yield {"type": "tool_result", "name": call["name"],
                       "result": json.loads(json.dumps(result, default=str))}
                history.append({"role": "tool", "tool_call_id": call["id"],
                                "content": json.dumps(result, default=str)[:8000]})

        yield {"type": "reply",
               "text": "I hit my tool-call limit on that one — try breaking the request "
                       "into smaller steps."}

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def team_roster(self) -> list[dict]:
        return [
            {"name": a.name, "description": a.description,
             "tools": [t["name"].split("__", 1)[1] for t in a.tool_declarations()],
             "generated": a.__class__.__module__.startswith("server.agents.generated")}
            for a in self.agents.values()
        ]
