"""Parsing JSON out of model output, which is never quite JSON.

Models fence their JSON, preface it with "Here's the analysis:", or trail a
closing remark after the final brace. Every agent that asks for structured
output needs the same forgiveness, so it lives here once.
"""
from __future__ import annotations

import json
from typing import Any


def loads(text: str, default: Any = None) -> Any:
    """Best-effort parse. Returns `default` rather than raising."""
    raw = (text or "").strip()
    if not raw:
        return default if default is not None else {}

    if raw.startswith("```"):
        lines = raw.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
        raw = raw.removeprefix("json").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost brace/bracket pair — handles prose on both sides.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                continue

    return default if default is not None else {}
