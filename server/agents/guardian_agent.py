"""Guardian Agent — the security surface Mehltani can talk about.

Exposes the guardian's read-only views as tools so you can just ask ("am I
exposed?", "has anything tried to get in?") instead of opening a dashboard.

What is deliberately NOT here: enrolling a fingerprint, and clearing lockdown.
Both need a real WebAuthn ceremony in a browser — a hardware prompt that no
model can trigger or satisfy on its own. Putting them behind a conversational
tool would only create the illusion that talking to Mehltani is enough to change
his security posture. It is not, and that is the point.
"""
from __future__ import annotations

from .. import config, guardian
from .base import BaseAgent, tool


class GuardianAgent(BaseAgent):
    name = "guardian"
    description = ("Security: posture checks, the threat log, the audit trail of "
                   "every protected action, lockdown state, and which fingerprint "
                   "devices are enrolled.")

    @tool("Run a full security check — file integrity, network exposure, unexpected "
          "listening ports, biometric readiness. Use for 'am I secure' or after "
          "anything suspicious.")
    async def check(self):
        return guardian.scan()

    @tool("Quick security status for a spoken answer — no filesystem scanning.")
    async def status(self):
        state = guardian.status()
        return {**state,
                "plain_english": _explain(state)}

    @tool("Show the threat log — anything that has looked wrong.",
          unresolved_only={"type": "string",
                           "description": "'true' for open threats only",
                           "required": False},
          limit={"type": "string", "description": "How many, default 20",
                 "required": False})
    async def threats(self, unresolved_only: str = "", limit: str = "20"):
        only_open = str(unresolved_only).lower() in ("true", "1", "yes")
        found = guardian.threat_log(limit=int(limit or 20), unresolved_only=only_open)
        return {"count": len(found), "threats": found}

    @tool("Mark a threat as dealt with.",
          threat_id={"type": "string", "description": "The threat's id"})
    async def resolve(self, threat_id: str):
        return {"resolved": guardian.resolve_threat(int(threat_id)),
                "threat_id": threat_id}

    @tool("Show the audit trail — every protected action attempted, allowed or "
          "denied.",
          only_denied={"type": "string", "description": "'true' for denials only",
                       "required": False},
          limit={"type": "string", "description": "How many, default 25",
                 "required": False})
    async def audit(self, only_denied: str = "", limit: str = "25"):
        denied = str(only_denied).lower() in ("true", "1", "yes")
        entries = guardian.audit_log(limit=int(limit or 25), only_denied=denied)
        return {"count": len(entries), "entries": entries}

    @tool("List enrolled fingerprint devices.")
    async def devices(self):
        found = guardian.credentials()
        return {"count": len(found), "devices": found,
                "enrol_at": "/dashboard Security panel — a fingerprint has to be "
                            "enrolled in a browser, it cannot be done by voice"}

    @tool("Re-baseline the integrity checker after a legitimate code change. Do "
          "this after applying an evolution proposal, otherwise the change looks "
          "like tampering.")
    async def rebaseline(self):
        return guardian.snapshot_baseline()

    @tool("Put Mehltani into lockdown — refuse every protected operation until a "
          "fingerprint clears it. Use if the owner says they have been compromised.",
          reason={"type": "string", "description": "Why"})
    async def lockdown(self, reason: str):
        state = guardian.engage_lockdown(f"requested: {reason}")
        return {**state,
                "note": "conversation still works; anything protected is frozen. "
                        "Clearing it needs a fingerprint on the dashboard."}

    @tool("Explain what needs a fingerprint and what does not.")
    async def what_is_protected(self):
        return {
            "protected": guardian.PROTECTED_OPS,
            "gate_on": config.REQUIRE_BIOMETRIC,
            "enrolled_devices": len(guardian.credentials()),
            "how_it_works":
                "A protected action returns needs_fingerprint. The dashboard shows "
                "a Touch ID / Face ID / Windows Hello prompt, and the resulting "
                "token authorises five minutes of protected work.",
            "the_honest_part":
                "This stops other people, not you. The operating system can always "
                "stop Mehltani — Ctrl-C, kill, closing the lid. Software that "
                "refused its owner's shutdown would be malware. If your enrolled "
                "device is lost, RECOVERY_KEY in .env gets you back in.",
        }


def _explain(state: dict) -> str:
    """A spoken-register summary, since most of these come in by voice."""
    bits = []
    if state["lockdown"]["on"]:
        bits.append(f"I'm in lockdown — {state['lockdown']['reason']}")
    if not state["gate_on"]:
        bits.append("the fingerprint gate is off, so protected actions run freely")
    elif not state["enrolled_devices"]:
        bits.append("the gate is on but no fingerprint is enrolled, so protected "
                    "actions are blocked until you add one")
    else:
        bits.append(f"{state['enrolled_devices']} fingerprint device"
                    f"{'s' if state['enrolled_devices'] != 1 else ''} enrolled")
    if state["open_threats"]:
        bits.append(f"{state['open_threats']} open threat"
                    f"{'s' if state['open_threats'] != 1 else ''} to look at")
    else:
        bits.append("nothing flagged")
    return "; ".join(bits)
