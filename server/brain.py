"""The brain — whichever model you actually have a key for.

Atlas runs on Gemini or on OpenAI. Everything that needs a model goes through
this module, so one key is enough to get the whole workspace working: the
orchestrator's tool calling, reading receipts from photos, merging the
council's answers, and checking live prices.

Selection is automatic (`BRAIN_PROVIDER=auto`): Gemini if you have that key,
otherwise OpenAI. Set BRAIN_PROVIDER explicitly to pin one.
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

import httpx

from . import config

TIMEOUT = 120.0


class NoBrain(RuntimeError):
    """Raised when nothing is configured — the message is shown to the user."""


def provider() -> str:
    """Which brain is driving: 'gemini', 'openai', or '' when neither is set."""
    pinned = (config.BRAIN_PROVIDER or "auto").lower()
    if pinned == "gemini":
        return "gemini" if config.GEMINI_API_KEY else ""
    if pinned == "openai":
        return "openai" if config.OPENAI_API_KEY else ""
    if config.GEMINI_API_KEY:
        return "gemini"
    if config.OPENAI_API_KEY:
        return "openai"
    return ""


def model_name() -> str:
    return config.GEMINI_MODEL if provider() == "gemini" else config.OPENAI_MODEL


def require() -> str:
    name = provider()
    if not name:
        raise NoBrain("no model key configured — add GEMINI_API_KEY or "
                      "OPENAI_API_KEY in Settings ⚙")
    return name


def _openai_headers() -> dict:
    return {"Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "content-type": "application/json"}


# ── plain completion ──────────────────────────────────────────────

async def complete(prompt: str, max_tokens: int = 1024) -> str:
    """One question, one answer, no tools."""
    if require() == "gemini":
        from google import genai

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL, contents=prompt)
        return (response.text or "").strip()

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{config.OPENAI_BASE_URL}/chat/completions", headers=_openai_headers(),
            json={"model": config.OPENAI_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]})
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return (choices[0]["message"].get("content") or "").strip() if choices else ""


# ── vision ────────────────────────────────────────────────────────

async def look(image: Path, prompt: str, max_tokens: int = 2048) -> str:
    """Ask the brain about an image — OCR, receipt extraction, whatever."""
    import base64

    raw = image.read_bytes()
    mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
    raw, mime = shrink(raw, mime)

    if require() == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[types.Part.from_bytes(data=raw, mime_type=mime), prompt])
        return (response.text or "").strip()

    data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{config.OPENAI_BASE_URL}/chat/completions", headers=_openai_headers(),
            json={"model": config.OPENAI_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": [
                      {"type": "text", "text": prompt},
                      {"type": "image_url", "image_url": {"url": data_uri}}]}]})
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return (choices[0]["message"].get("content") or "").strip() if choices else ""


def shrink(raw: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale a 12-megapixel phone photo before sending it upstream.

    Pillow is optional: without it the original bytes go up unchanged, which
    still works, just slower and more expensive.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return raw, mime
    try:
        image = Image.open(io.BytesIO(raw))
        image.thumbnail((1600, 1600))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue(), "image/jpeg"
    except Exception:
        return raw, mime


# ── grounded answers (live web) ───────────────────────────────────

async def web_answer(question: str) -> str:
    """Answer using live web results.

    Never falls back to answering from memory: a shopping companion that
    invents a price is worse than one that admits it can't check. If the
    backend has no search, this raises and the caller says so plainly.
    """
    if require() == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL, contents=question,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]))
        return (response.text or "").strip()

    # OpenAI: the Responses API carries the hosted web_search tool.
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{config.OPENAI_BASE_URL}/responses", headers=_openai_headers(),
            json={"model": config.OPENAI_MODEL, "input": question,
                  "tools": [{"type": "web_search"}]})
        if response.status_code >= 400:
            raise RuntimeError(
                f"live search is not available on {config.OPENAI_MODEL} "
                f"(HTTP {response.status_code}). Add a GEMINI_API_KEY for grounded "
                "price checks, or switch OPENAI_MODEL to one with web search.")
        return _responses_text(response.json())


def _responses_text(body: dict) -> str:
    """Pull the text out of a Responses API payload, shape-tolerantly."""
    if isinstance(body.get("output_text"), str) and body["output_text"].strip():
        return body["output_text"].strip()
    chunks = []
    for item in body.get("output") or []:
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


# ── tool-calling chat (the orchestrator's loop) ───────────────────

async def openai_chat(messages: list[dict], tools: list[dict]) -> dict:
    """One OpenAI turn. Returns the raw assistant message dict.

    The caller owns the history, which keeps the orchestrator's loop identical
    in shape to the Gemini one.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        payload = {"model": config.OPENAI_MODEL, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = await client.post(
            f"{config.OPENAI_BASE_URL}/chat/completions", headers=_openai_headers(), json=payload)
        response.raise_for_status()
        choices = response.json().get("choices") or []
        return choices[0]["message"] if choices else {"content": ""}


def parse_tool_calls(message: dict) -> list[dict]:
    """Normalise OpenAI tool calls into {id, name, args}."""
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = {}
        calls.append({"id": call.get("id") or function.get("name", ""),
                      "name": function.get("name", ""), "args": args})
    return calls


async def check() -> dict:
    """Is the selected brain actually reachable? Used by the Settings panel."""
    name = provider()
    if not name:
        return {"on": False, "detail": "no Gemini or OpenAI key"}
    try:
        if name == "gemini":
            from google import genai

            client = genai.Client(api_key=config.GEMINI_API_KEY)
            await client.aio.models.get(model=config.GEMINI_MODEL)
        else:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"{config.OPENAI_BASE_URL}/models/{config.OPENAI_MODEL}",
                    headers=_openai_headers())
                response.raise_for_status()
        return {"on": True, "detail": f"connected · {name} · {model_name()}"}
    except Exception as exc:
        return {"on": False, "detail": f"{name} key set but check failed: "
                                       f"{type(exc).__name__}"}
