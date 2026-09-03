"""Evolution Agent — Mehltani rewriting himself, and building new specialists.

Two capabilities, one agent:

  * self-modification — propose a change to his own source, verify it against
    the test suite in a sandbox, show you the diff, and ship it once you approve
    with a fingerprint. See evolution.py for why each of those steps exists.
  * subagent creation — design, validate and register a brand-new specialist
    while running. See factory.py for the sandbox rules.

The tool descriptions are written to make the model *follow the pipeline* rather
than reach for the last step. `apply` will refuse an unverified proposal anyway,
but a model that understands why tends to produce better proposals.
"""
from __future__ import annotations

from .. import evolution, factory, guardian
from .base import BaseAgent, tool


class EvolutionAgent(BaseAgent):
    name = "evolution"
    description = ("Mehltani's own source code: propose a change, verify it against "
                   "the test suite in a sandbox, show the diff, and ship it once "
                   "the owner approves with a fingerprint. Also designs and "
                   "registers brand-new subagents at runtime.")

    # ── self-modification ─────────────────────────────────────────

    @tool(
        "Propose a change to Mehltani's own code. This only drafts it — nothing "
        "runs and nothing is written to the live tree. Always follow with verify.",
        goal={"type": "string", "description": "What the change should achieve"},
        path={"type": "string",
              "description": "Repo-relative file, e.g. server/agents/style_agent.py"},
        rationale={"type": "string", "description": "Why this is the right change",
                   "required": False},
    )
    async def propose(self, goal: str, path: str, rationale: str = ""):
        try:
            proposal = await evolution.propose(goal, path, rationale=rationale)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"proposal_id": proposal["id"], "path": proposal["path"],
                "status": proposal["status"], "goal": goal,
                "lines": len(proposal["new_source"].splitlines()),
                "next": "call evolution__verify to run the test suite against it"}

    @tool(
        "Verify a proposal: copy the whole repo to a scratch directory, apply the "
        "change there, and run the test suite against the copy. The live code is "
        "untouched. A proposal must pass this before it can be applied.",
        proposal_id={"type": "string", "description": "The proposal's id"},
    )
    async def verify(self, proposal_id: str):
        return await evolution.verify(int(proposal_id))

    @tool("Show the diff for a proposal so the owner can read what would change.",
          proposal_id={"type": "string", "description": "The proposal's id"})
    async def show_diff(self, proposal_id: str):
        text = evolution.diff(int(proposal_id))
        record = evolution.get(int(proposal_id))
        if not record:
            return {"error": f"no proposal {proposal_id}"}
        return {"proposal_id": int(proposal_id), "path": record["path"],
                "goal": record["goal"], "status": record["status"],
                "diff": text or "(no textual change)",
                "test_output": record["test_output"][-1500:]}

    @tool(
        "Ship a verified proposal to the live code. Requires the owner's "
        "fingerprint, and commits to git so it can be rolled back.",
        proposal_id={"type": "string", "description": "The proposal's id"},
        presence_token={"type": "string", "description": "Biometric token",
                        "required": False},
    )
    async def apply(self, proposal_id: str, presence_token: str = ""):
        try:
            return evolution.apply(int(proposal_id), presence_token=presence_token)
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc),
                    "proposal_id": int(proposal_id)}

    @tool(
        "Roll back an applied change, restoring the previous version of the file.",
        proposal_id={"type": "string", "description": "The proposal's id"},
        presence_token={"type": "string", "description": "Biometric token",
                        "required": False},
    )
    async def rollback(self, proposal_id: str, presence_token: str = ""):
        try:
            return evolution.rollback(int(proposal_id), presence_token=presence_token)
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc)}

    @tool("List past and pending proposals.",
          status={"type": "string",
                  "description": "draft, verified, rejected, applied or reverted",
                  "required": False})
    async def history(self, status: str = ""):
        return {"proposals": evolution.history(status=status),
                "stats": evolution.stats()}

    @tool("Read one of Mehltani's own source files.",
          path={"type": "string", "description": "Repo-relative path"})
    async def read_own_source(self, path: str):
        try:
            source = evolution.read_source(path)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"path": path, "lines": len(source.splitlines()), "source": source}

    # ── building new subagents ────────────────────────────────────

    @tool(
        "Design and register a brand-new subagent. Use when the team is missing a "
        "skill entirely. The generated code is validated against an import "
        "allowlist and an AST scan before it is written, and it joins the team "
        "immediately — no restart.",
        purpose={"type": "string",
                 "description": "What the new specialist should be able to do"},
        agent_name={"type": "string",
                    "description": "Short lowercase name, e.g. 'fabric'",
                    "required": False},
        tools={"type": "string",
               "description": "Comma-separated tools it should expose",
               "required": False},
    )
    async def create_subagent(self, purpose: str, agent_name: str = "",
                              tools: str = ""):
        try:
            design = await factory.design(purpose, agent_name=agent_name, tools=tools)
        except factory.Rejected as exc:
            return {"error": f"the generated agent failed validation: {exc}",
                    "note": "nothing was written to disk"}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        written = factory.write_agent(design["source"], design["agent_name"])
        return {"created": written["agent_name"], "tools": written["tools"],
                "file": written["path"], "purpose": purpose,
                "next": "it's on the team now — later tool calls in this same "
                        "conversation can already reach it. To have the model see "
                        "its tools in its own tool list, start a new session "
                        "(reconnect, or say 'reset')."}

    @tool("List the subagents Mehltani has written for himself.")
    async def list_subagents(self):
        generated = factory.list_generated()
        return {"count": len(generated), "agents": generated,
                "directory": "server/agents/generated/"}

    @tool("Read the source of a generated subagent.",
          agent_name={"type": "string", "description": "The agent's name"})
    async def read_subagent(self, agent_name: str):
        source = factory.source_of(agent_name)
        if not source:
            return {"error": f"no generated agent named {agent_name!r}"}
        return {"agent": agent_name, "source": source}

    @tool(
        "Delete a generated subagent. Requires a fingerprint.",
        agent_name={"type": "string", "description": "The agent's name"},
        presence_token={"type": "string", "description": "Biometric token",
                        "required": False},
    )
    async def remove_subagent(self, agent_name: str, presence_token: str = ""):
        try:
            return factory.remove(agent_name, presence_token=presence_token)
        except guardian.Denied as exc:
            return {"needs_fingerprint": True, "error": str(exc)}
