"""Council Agent — one question, every AI companion you own, all at once.

Deliberately provider-neutral: each companion is reached over plain HTTP, so
Claude, ChatGPT, Gemini, OpenRouter and any OpenAI-compatible endpoint you run
locally (Ollama, LM Studio, a Cursor-style gateway, your own proxy) all plug in
the same way. Add one line to COMPANION_ENDPOINTS and it joins the council.

What this is not: it does not drive the ChatGPT/Gemini/Cursor *desktop apps*.
Those have no public automation surface. It talks to the same models through
their APIs, which is the part that is actually controllable.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from .. import brain, config
from .base import BaseAgent, tool

TIMEOUT = 90.0


def _openai_style(name: str, base_url: str, model: str, key: str) -> dict:
    return {"name": name, "kind": "openai", "base_url": base_url.rstrip("/"),
            "model": model, "key": key}


def companions() -> list[dict]:
    """Every companion that is configured right now, newest config wins."""
    out: list[dict] = []
    if config.ANTHROPIC_API_KEY:
        out.append({"name": "claude", "kind": "anthropic",
                    "base_url": "https://api.anthropic.com",
                    "model": config.ANTHROPIC_MODEL, "key": config.ANTHROPIC_API_KEY})
    if config.OPENAI_API_KEY:
        # Honour OPENAI_BASE_URL: if the key belongs to a proxy or an Azure
        # gateway, the council must not send it to api.openai.com.
        out.append(_openai_style("chatgpt", config.OPENAI_BASE_URL,
                                 config.OPENAI_MODEL, config.OPENAI_API_KEY))
    if config.GEMINI_API_KEY:
        out.append({"name": "gemini", "kind": "gemini", "base_url": "",
                    "model": config.GEMINI_MODEL, "key": config.GEMINI_API_KEY})
    if config.OPENROUTER_API_KEY:
        out.append(_openai_style("openrouter", "https://openrouter.ai/api/v1",
                                 config.OPENROUTER_MODEL, config.OPENROUTER_API_KEY))
    out.extend(_custom_companions())
    return out


def _custom_companions() -> list[dict]:
    """Parse COMPANION_ENDPOINTS: `name|base_url|model|api_key`, comma-separated.

    Any OpenAI-compatible server works — a local Ollama, LM Studio, your own
    router, or a self-hosted agent that speaks /chat/completions.
    """
    out = []
    for entry in (config.COMPANION_ENDPOINTS or "").split(","):
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
            name, base_url, model = parts[0], parts[1], parts[2]
            key = parts[3] if len(parts) > 3 else ""
            out.append(_openai_style(name, base_url, model, key))
    return out


# ── per-provider calls ────────────────────────────────────────────

async def _ask_anthropic(client: httpx.AsyncClient, comp: dict, prompt: str,
                         max_tokens: int) -> str:
    # Note: current Claude models reject temperature/top_p — send neither.
    response = await client.post(
        f"{comp['base_url']}/v1/messages",
        headers={"x-api-key": comp["key"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": comp["model"], "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "refusal":
        return "(declined this request)"
    return "".join(b.get("text", "") for b in body.get("content", [])
                   if b.get("type") == "text").strip()


async def _ask_openai(client: httpx.AsyncClient, comp: dict, prompt: str,
                      max_tokens: int) -> str:
    headers = {"content-type": "application/json"}
    if comp["key"]:
        headers["Authorization"] = f"Bearer {comp['key']}"
    response = await client.post(
        f"{comp['base_url']}/chat/completions", headers=headers,
        json={"model": comp["model"], "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
    )
    response.raise_for_status()
    choices = response.json().get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


async def _ask_gemini(comp: dict, prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=comp["key"])
    response = await client.aio.models.generate_content(
        model=comp["model"], contents=prompt)
    return (response.text or "").strip()


async def ask_one(comp: dict, prompt: str, max_tokens: int = 1024) -> dict:
    """Ask a single companion; never raises — failures come back as data."""
    started = time.monotonic()
    try:
        if comp["kind"] == "gemini":
            answer = await asyncio.wait_for(_ask_gemini(comp, prompt), timeout=TIMEOUT)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                call = _ask_anthropic if comp["kind"] == "anthropic" else _ask_openai
                answer = await call(client, comp, prompt, max_tokens)
        return {"companion": comp["name"], "model": comp["model"], "ok": True,
                "answer": answer, "seconds": round(time.monotonic() - started, 1)}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response is not None else ""
        return {"companion": comp["name"], "model": comp["model"], "ok": False,
                "error": f"HTTP {exc.response.status_code}: {detail}",
                "seconds": round(time.monotonic() - started, 1)}
    except asyncio.TimeoutError:
        return {"companion": comp["name"], "model": comp["model"], "ok": False,
                "error": f"timed out after {TIMEOUT:.0f}s"}
    except Exception as exc:
        return {"companion": comp["name"], "model": comp["model"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}


async def broadcast(prompt: str, only: list[str] | None = None,
                    max_tokens: int = 1024) -> list[dict]:
    """Fan one prompt out to every configured companion, in parallel."""
    targets = companions()
    if only:
        wanted = {n.strip().lower() for n in only}
        targets = [c for c in targets if c["name"].lower() in wanted]
    if not targets:
        return []
    return list(await asyncio.gather(*(ask_one(c, prompt, max_tokens) for c in targets)))


class CouncilAgent(BaseAgent):
    name = "council"
    description = ("Talks to every AI companion you own at once — Claude, ChatGPT, "
                   "Gemini, OpenRouter and any OpenAI-compatible endpoint you add. "
                   "Broadcast a prompt to all of them, ask one specifically, or have "
                   "their answers merged into a single verdict.")

    @tool("List every AI companion that is configured and reachable right now.")
    async def list_companions(self):
        found = companions()
        return {"count": len(found),
                "companions": [{"name": c["name"], "model": c["model"],
                                "kind": c["kind"]} for c in found]} if found else \
               {"count": 0, "companions": [],
                "hint": "add ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY, "
                        "or COMPANION_ENDPOINTS, in Settings"}

    @tool(
        "Send the same question to every AI companion at once and return all answers "
        "side by side. Use when the user wants a second (and third) opinion.",
        prompt={"type": "string", "description": "The question to broadcast"},
        only={"type": "string",
              "description": "Comma-separated companion names to limit the broadcast",
              "required": False},
    )
    async def ask_all(self, prompt: str, only: str = ""):
        names = [n for n in only.split(",") if n.strip()] if only else None
        results = await broadcast(prompt, names)
        if not results:
            return {"error": "no AI companions are configured yet — add keys in Settings"}
        return {"prompt": prompt, "answered": sum(1 for r in results if r["ok"]),
                "results": results}

    @tool(
        "Ask one specific AI companion by name.",
        companion={"type": "string", "description": "Name from list_companions"},
        prompt={"type": "string", "description": "The question"},
    )
    async def ask(self, companion: str, prompt: str):
        results = await broadcast(prompt, [companion])
        if not results:
            return {"error": f"no companion named {companion!r} is configured"}
        return results[0]

    @tool(
        "Broadcast a question to every companion, then merge their answers into one "
        "verdict that flags where they agree and where they disagree.",
        prompt={"type": "string", "description": "The question to put to the council"},
    )
    async def consensus(self, prompt: str):
        results = await broadcast(prompt)
        answered = [r for r in results if r["ok"] and r["answer"]]
        if not answered:
            return {"error": "no companion answered — check the keys in Settings",
                    "results": results}
        if len(answered) == 1:
            return {"prompt": prompt, "verdict": answered[0]["answer"],
                    "sources": [answered[0]["companion"]], "results": results}
        if not brain.provider():
            return {"prompt": prompt, "results": results,
                    "note": "answers returned unmerged — merging needs a Gemini or "
                            "OpenAI key"}

        transcript = "\n\n".join(
            f"### {r['companion']} ({r['model']})\n{r['answer']}" for r in answered)
        verdict = await brain.complete(
            f"Several AI assistants answered the same question. Write one short "
            f"spoken-style answer that states what they agree on, and names any point "
            f"where they disagree. Do not use markdown.\n\n"
            f"QUESTION: {prompt}\n\n{transcript}")
        return {"prompt": prompt, "verdict": verdict,
                "sources": [r["companion"] for r in answered], "results": results}
