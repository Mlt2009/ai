#!/usr/bin/env python3
"""Artist — AI companion CLI.

Start an interactive chat session with Artist directly from the terminal.

Quick start::

    python artist.py

Commands available during the chat:
  /reset      — clear conversation history and start fresh
  /compress   — manually compress context to save tokens
  /team       — show the active agent roster
  /prompts    — list available creative prompt themes
  /help       — show this help text
  exit / quit — end the session
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Ensure the repo root is on the path so ``artist`` and ``server`` packages
# resolve correctly regardless of where the script is invoked from.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from artist.core import Artist  # noqa: E402  (after sys.path setup)

# ── Helpers ────────────────────────────────────────────────────────────────────

_HELP = """\
Commands
  /reset      clear conversation history
  /compress   summarise context to reduce token usage
  /team       show Artist's active agent roster
  /prompts    list creative prompt themes
  /help       show this message
  exit/quit   end the session
"""

_BANNER = """\
╔══════════════════════════════════════════════════════╗
║         A R T I S T  —  AI Companion  v1.0           ║
║  Chat · Coding · Swarm Coordination · Token-Saving   ║
╚══════════════════════════════════════════════════════╝
Type /help for commands, or just start chatting.
"""


def _print_team(companion: Artist) -> None:
    print()
    for entry in companion.team_roster():
        tools = ", ".join(entry["tools"])
        print(f"  [{entry['name']}]  {entry['description']}")
        print(f"          tools: {tools}")
    print()


# ── Main loop ──────────────────────────────────────────────────────────────────

async def _run() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(
            "Warning: GEMINI_API_KEY is not set.\n"
            "Artist will run in offline mode — responses will be limited.\n"
            "Set the key in your .env file and restart.\n"
        )

    companion = Artist(api_key=api_key)

    print(_BANNER)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nArtist: Goodbye, Sir.")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("exit", "quit"):
            print("Artist: Goodbye, Sir.")
            break

        if lower == "/help":
            print(_HELP)
            continue

        if lower == "/reset":
            companion.reset()
            print("Artist: Session cleared. Ready for fresh directives, Sir.\n")
            continue

        if lower == "/compress":
            summary = companion.compress_now()
            if summary:
                print(f"Artist: Context compressed. Summary:\n  {summary}\n")
            else:
                print("Artist: Nothing to compress yet, Sir.\n")
            continue

        if lower == "/team":
            _print_team(companion)
            continue

        if lower == "/prompts":
            from artist.prompts_data import THEMES
            print(f"\n  Available themes ({len(THEMES)}): {', '.join(THEMES)}")
            print("  Ask Artist to search or retrieve any prompt by number (1–50).\n")
            continue

        # Normal chat turn — stream events, print reply.
        print("Artist: ", end="", flush=True)
        try:
            async for event in companion.respond(user_input):
                if event["type"] == "reply":
                    print(event["text"])
                elif event["type"] == "tool":
                    print(f"[calling {event['name']}…]", flush=True)
        except Exception as exc:
            print(f"\n[Error: {type(exc).__name__}: {exc}]")
            companion.reset()

        print()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
