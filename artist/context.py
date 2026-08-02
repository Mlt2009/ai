"""Token-saving context compressor for Artist.

When a conversation grows long, Artist can compress the accumulated turns
into a concise summary so the model stays focused and token costs stay low.
The summary is folded back into the next session's system instruction.
"""
from __future__ import annotations

COMPRESS_AFTER = 12  # summarise after this many user turns

_COMPRESS_PROMPT = """\
Summarise the conversation below into a concise, information-dense paragraph
(max 200 words). Preserve all important facts, decisions, code snippets, and
open threads. Omit small-talk.

{history}
"""


class ContextCompressor:
    """Tracks conversation turns and compresses them when the threshold is hit.

    Usage::

        compressor = ContextCompressor(gemini_client, model_name)
        compressor.add("user", "How do I reverse a list in Python?")
        compressor.add("assistant", "Use `my_list[::-1]` or `list(reversed(…))`.")
        if compressor.should_compress():
            compressor.compress()           # calls Gemini; clears turns
        prefix = compressor.context_prefix()  # prepend to next system prompt
    """

    def __init__(self, client, model: str, threshold: int = COMPRESS_AFTER) -> None:
        self._client = client
        self._model = model
        self.threshold = threshold
        self.summary: str = ""       # compressed history of old turns
        self.turns: list[dict] = []  # recent, uncompressed turns

    # ── Public API ────────────────────────────────────────────────

    def add(self, role: str, text: str) -> None:
        """Record a single conversation turn."""
        self.turns.append({"role": role, "text": text[:2000]})

    def should_compress(self) -> bool:
        """Return True when the turn buffer has reached the compression threshold."""
        return len(self.turns) >= self.threshold

    def compress(self) -> str:
        """Call Gemini to summarise buffered turns; store the result and clear
        the buffer.  Returns the new summary string."""
        if not self.turns:
            return self.summary
        history_parts = [f"{t['role'].upper()}: {t['text']}" for t in self.turns]
        history = "\n".join(history_parts)
        if self.summary:
            history = f"[Previous summary]\n{self.summary}\n\n[New turns]\n{history}"
        prompt = _COMPRESS_PROMPT.format(history=history)
        response = self._client.models.generate_content(
            model=self._model, contents=prompt
        )
        self.summary = (response.text or "").strip()
        self.turns.clear()
        return self.summary

    def context_prefix(self) -> str:
        """Return a compact string to prepend to the system instruction."""
        if self.summary:
            return f"\n\n[Conversation summary so far]\n{self.summary}"
        return ""

    def reset(self) -> None:
        """Discard all history (used when the user requests a fresh start)."""
        self.summary = ""
        self.turns.clear()
