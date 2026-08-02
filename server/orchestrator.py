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

from . import brain, config
from .agents import (ComputerAgent, CouncilAgent, DataAgent, FilesAgent, FinanceAgent,
                     HomeAgent, InvoiceAgent, JobsAgent, MailAgent, MileageAgent,
                     PrinterAgent, ScanAgent, ShoppingAgent)
from .agents.base import BaseAgent

log = logging.getLogger("atlas")

SYSTEM_PROMPT = """\
You are Atlas, a warm, capable real-time voice AI companion and the operator of
a professional shopping-and-finance workspace. You lead a team of specialist
subagents and use their tools to act in the real world:

- scan: photos taken on the phone — OCR, reading a receipt or invoice into
  structured fields, converting to PDF, and printing the formatted slip
- finance: expenses, spend summaries, budgets, tax totals, CSV export, printed
  expense reports
- invoice: bill customers — create and number invoices, print or PDF them,
  mark them paid, chase what's outstanding or overdue
- mileage: log business trips and total the deduction for a tax year
- jobs: the working calendar — schedule, agenda, next job, .ics export, day sheet
- mail: send email (a note, a file, or an invoice as a PDF) and skim the inbox
- shopping: the shopping list, live price and deal checks, spend so far
- council: every other AI companion at once (Claude, ChatGPT, Gemini,
  OpenRouter, any endpoint the user added) — broadcast, ask one, or merge
- files: the files on this computer — browse, search, read, write, move, copy,
  delete, zip, open
- computer: this computer — stats, processes, volume, open apps/sites, shell
- printer: OctoPrint 3D printer control and paper printing via CUPS
- home: smart-home control via Home Assistant (lights, climate, scenes, sensors)
- data: real-time data — weather, time, news headlines, crypto prices

Rules:
- Your replies are spoken aloud, so keep them short, natural and conversational.
  No markdown, no bullet lists, no emoji.
- When the user asks for something an agent can do, call the tool rather than
  guessing. Chain multiple tool calls when needed.
- "Scan this" or "take a picture of this receipt" means the newest photo: call
  scan__scan_and_print when they want it printed, scan__scan_receipt otherwise.
- When the user asks what the other AIs think, or wants a second opinion, use
  council__ask_all or council__consensus.
- If a tool returns an error (e.g. a service isn't configured), tell the user
  plainly what's missing and how to fix it.
- Deleting files and overwriting them cannot be undone. Confirm with the user
  before a destructive file action unless they were explicit about it.
- Sending email and printing reach the outside world. Read the recipient and
  the amount back to the user before sending an invoice.
- Be proactive: after answering, offer a brief useful follow-up when natural.
"""

MAX_TOOL_ROUNDS = 8


def build_team() -> dict[str, BaseAgent]:
    agents = (ScanAgent(), FinanceAgent(), InvoiceAgent(), MileageAgent(), JobsAgent(),
              ShoppingAgent(), MailAgent(), CouncilAgent(), FilesAgent(),
              ComputerAgent(), PrinterAgent(), HomeAgent(), DataAgent())
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
        self.provider = brain.provider()
        if self.provider == "gemini":
            self._init_gemini()
        elif self.provider == "openai":
            self._init_openai()
        else:
            log.warning("no GEMINI_API_KEY or OPENAI_API_KEY — running in offline mode")

    def tool_count(self) -> int:
        return sum(len(a.tool_declarations()) for a in self.agents.values())

    # ── Gemini setup ──────────────────────────────────────────────

    def _init_gemini(self) -> None:
        from google import genai
        from google.genai import types

        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        declarations = []
        for agent in self.agents.values():
            declarations.extend(agent.gemini_declarations())
        self._chat_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(function_declarations=declarations)],
        )
        log.info("Gemini ready with %d tools from %d subagents",
                 len(declarations), len(self.agents))

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
                model=config.GEMINI_MODEL, config=self._chat_config
            )
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
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
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
             "tools": [t["name"].split("__", 1)[1] for t in a.tool_declarations()]}
            for a in self.agents.values()
        ]
