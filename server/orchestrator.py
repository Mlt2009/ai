"""Atlas — the orchestrator that runs the subagent team.

One Gemini-powered brain sits on top; every specialist subagent registers
its tools with it. Gemini decides which agent/tool to call (function
calling), the orchestrator executes it, feeds the result back, and loops
until Gemini produces a final spoken answer.

Uses the modern `google-genai` SDK — the same one the A.D.A. desktop
frontend uses for the Gemini Live API, so both frontends share one team.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from . import config
from .agents import ComputerAgent, DataAgent, HomeAgent, PrinterAgent
from .agents.base import BaseAgent

log = logging.getLogger("atlas")

SYSTEM_PROMPT = """\
You are Atlas, a warm, capable real-time voice AI companion. You lead a team
of specialist subagents and use their tools to act in the real world:

- home: smart-home control via Home Assistant (lights, climate, scenes, sensors)
- printer: OctoPrint 3D printer control and paper printing via CUPS
- computer: this computer — stats, processes, volume, open apps/sites, shell
- data: real-time data — weather, time, news headlines, crypto prices

Rules:
- Your replies are spoken aloud, so keep them short, natural and conversational.
  No markdown, no bullet lists, no emoji.
- When the user asks for something an agent can do, call the tool rather than
  guessing. Chain multiple tool calls when needed.
- If a tool returns an error (e.g. a service isn't configured), tell the user
  plainly what's missing and how to fix it.
- Be proactive: after answering, offer a brief useful follow-up when natural.
"""

MAX_TOOL_ROUNDS = 6


def build_team() -> dict[str, BaseAgent]:
    agents = (HomeAgent(), PrinterAgent(), ComputerAgent(), DataAgent())
    return {a.name: a for a in agents}


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
        if config.GEMINI_API_KEY:
            self._init_gemini()
        else:
            log.warning("GEMINI_API_KEY not set — running in offline mode")

    # ── Gemini setup ──────────────────────────────────────────────

    def _init_gemini(self) -> None:
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        declarations = []
        for agent in self.agents.values():
            declarations.extend(agent.tool_declarations())
        self._chat_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(function_declarations=declarations)],
        )
        log.info("Gemini ready with %d tools from %d subagents",
                 len(declarations), len(self.agents))

    def _chat(self, session_id: str):
        chat = self._sessions.get(session_id)
        if chat is None:
            chat = self._client.aio.chats.create(
                model=config.GEMINI_MODEL, config=self._chat_config
            )
            self._sessions[session_id] = chat
        return chat

    # ── Main entry: one user turn ─────────────────────────────────

    async def respond(self, session_id: str, text: str) -> AsyncIterator[dict]:
        """Yield events for one user turn: {'type': 'tool'|'tool_result'|'reply', ...}."""
        if self._client is None:
            yield {"type": "reply",
                   "text": "I'm running without a brain right now — add your "
                           "GEMINI_API_KEY to the .env file and restart me."}
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
                yield {"type": "tool_result", "name": fc.name,
                       "result": json.loads(json.dumps(result, default=str))}
                fn_parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": result}))
            message = fn_parts

        yield {"type": "reply",
               "text": "I hit my tool-call limit on that one — try breaking the request into smaller steps."}

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def team_roster(self) -> list[dict]:
        return [
            {"name": a.name, "description": a.description,
             "tools": [t["name"].split("__", 1)[1] for t in a.tool_declarations()]}
            for a in self.agents.values()
        ]
