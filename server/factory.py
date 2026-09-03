"""Factory — Mehltani writing brand-new subagents for himself at runtime.

When the team is missing a skill ("nobody here knows how to price vintage
Alaïa"), Mehltani designs a new specialist, writes its source, validates it,
and registers it into the live orchestrator without a restart.

The safety story is different from evolution.py and worth stating plainly.
Generated agents are *new* code with no test suite behind them, so instead of
"prove it passes tests" the rule is "prove it can't do much harm":

  * an import allowlist — a generated agent can reach the brain, the style
    profile, httpx and the standard library's safe corners. It cannot import
    `os`, `subprocess`, `socket`, `shutil`, or anything else that touches the
    machine directly. Those powers already exist on the hand-written computer
    and files agents, which are gated and audited.
  * an AST scan — no `eval`, `exec`, `compile`, `__import__`, no dunder
    attribute access. This is checked on the parsed tree, not with a regex, so
    it cannot be defeated by string tricks or whitespace.
  * import happens from a file on disk, never from a string. `importlib` on a
    real path keeps tracebacks honest and lets you open the generated file and
    read exactly what Mehltani wrote.
  * every generated agent is namespaced under `generated/` and can be deleted.
  * a generated agent can never take a hand-written agent's name — closing off
    a shadowing/collision path.

The validator runs before the file is written, so invalid source never lands on
disk at all.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import brain, config, guardian
from .agents.base import BaseAgent

log = logging.getLogger("factory")

GENERATED_DIR = Path(__file__).resolve().parent / "agents" / "generated"

# What a generated agent may import. Anything absent is a hard reject.
ALLOWED_IMPORTS = {
    "__future__", "annotations",
    "asyncio", "json", "math", "re", "time", "random", "textwrap",
    "datetime", "collections", "itertools", "statistics", "typing", "urllib.parse",
    "httpx",
    # relative imports back into the app
    "base", "brain", "style_memory", "ledger",
}

BANNED_CALLS = {"eval", "exec", "compile", "__import__", "open", "input",
                "globals", "locals", "vars", "getattr", "setattr", "delattr"}

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,24}$")

# Hand-written agent names a generated agent must never shadow.
RESERVED_NAMES = {"style", "photoshoot", "glam", "trend", "whatsapp", "workspace",
                  "scan", "finance", "shopping", "council", "files", "computer",
                  "printer", "home", "data", "guardian", "evolution"}

TEMPLATE_HINT = '''\
"""One-line purpose of this agent."""
from __future__ import annotations

from ..base import BaseAgent, tool
from ... import brain


class ExampleAgent(BaseAgent):
    name = "example"
    description = "What this specialist knows, in one sentence."

    @tool("What this tool does, phrased for a model deciding whether to call it.",
          subject={"type": "string", "description": "what to act on"},
          depth={"type": "string", "description": "quick or deep", "required": False})
    async def analyse(self, subject: str, depth: str = "quick"):
        answer = await brain.complete(f"...{subject}...")
        return {"subject": subject, "analysis": answer}
'''


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_dir() -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init = GENERATED_DIR / "__init__.py"
    if not init.exists():
        init.write_text('"""Subagents Mehltani wrote for himself. Safe to delete."""\n')
    return GENERATED_DIR


# ── validation ────────────────────────────────────────────────────

class Rejected(ValueError):
    """The generated source failed a safety check; it is never written."""


def _import_names(node: ast.AST) -> list[str]:
    names = []
    if isinstance(node, ast.Import):
        names.extend(alias.name.split(".")[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            names.append(node.module.split(".")[0])
        else:
            # `from ..base import ...` — level>0, module is None
            names.extend(alias.name for alias in node.names)
    return names


def validate(source: str, expected_name: str = "") -> dict:
    """Parse and inspect generated source. Raises Rejected with the reason."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Rejected(f"SyntaxError line {exc.lineno}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_names(node):
                if name not in ALLOWED_IMPORTS:
                    raise Rejected(
                        f"import of {name!r} is not allowed in a generated agent. "
                        f"Allowed: {', '.join(sorted(ALLOWED_IMPORTS))}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                raise Rejected(f"call to {node.func.id}() is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise Rejected(f"dunder attribute access ({node.attr}) is not allowed")

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    agent_classes = [c for c in classes
                     if any(getattr(b, "id", getattr(b, "attr", "")) == "BaseAgent"
                            for b in c.bases)]
    if not agent_classes:
        raise Rejected("no class subclassing BaseAgent was defined")

    cls = agent_classes[0]
    declared_name = ""
    for stmt in cls.body:
        if (isinstance(stmt, ast.Assign) and stmt.targets
                and getattr(stmt.targets[0], "id", "") == "name"
                and isinstance(stmt.value, ast.Constant)):
            declared_name = str(stmt.value.value)
    if not declared_name:
        raise Rejected("the agent class must set a `name` class attribute")
    if not NAME_RE.match(declared_name):
        raise Rejected(f"agent name {declared_name!r} must be lowercase letters, "
                       "digits and underscores, 3-25 characters")
    if declared_name in RESERVED_NAMES:
        raise Rejected(f"{declared_name!r} is a hand-written agent's name and "
                       "cannot be shadowed by a generated one")
    if expected_name and declared_name != expected_name:
        raise Rejected(f"declared name {declared_name!r} does not match the "
                       f"requested name {expected_name!r}")

    tools = [n.name for n in cls.body
             if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
             and any(isinstance(d, ast.Call) and getattr(d.func, "id", "") == "tool"
                     for d in n.decorator_list)]
    if not tools:
        raise Rejected("the agent defines no @tool methods, so it could never be called")

    return {"agent_name": declared_name, "class": cls.name, "tools": tools}


# ── designing ─────────────────────────────────────────────────────

async def design(purpose: str, agent_name: str = "", tools: str = "") -> dict:
    """Ask the brain to write a new subagent for a stated purpose."""
    if agent_name and agent_name.strip().lower() in RESERVED_NAMES:
        raise Rejected(f"{agent_name!r} is a hand-written agent's name — choose "
                       "a different name for the new specialist")
    name_hint = (f"The agent's `name` attribute must be exactly {agent_name!r}."
                 if agent_name else
                 "Choose a short lowercase `name` attribute that reads like a job title.")
    tool_hint = f"It should expose roughly these tools: {tools}." if tools else ""

    prompt = f"""\
Write a new Python subagent for an AI companion that works in fashion design,
hair, makeup and styling. Return ONLY the file contents — no markdown fence, no
commentary.

PURPOSE: {purpose}
{name_hint}
{tool_hint}

Follow this shape exactly:

{TEMPLATE_HINT}

Hard constraints — the file is rejected automatically if any is broken:
- You may import ONLY from: {', '.join(sorted(ALLOWED_IMPORTS))}
- No os, subprocess, socket, shutil, pathlib, sys, or file access of any kind.
- No eval, exec, compile, __import__, open, getattr, setattr.
- Every tool must be `async def` and return a dict.
- Every tool needs a @tool(...) decorator whose description tells a model when
  to call it, with a JSON-schema entry for each parameter.
- Use `await brain.complete(prompt)` for reasoning, `await brain.web_answer(q)`
  for anything that needs live web facts, and `await brain.look(path, prompt)`
  for images.
- Handle failure by returning {{"error": "..."}}, never by raising.
- Write real, working logic. Do not leave TODOs or placeholder returns.
"""
    source = _strip_fence(await brain.complete(prompt, max_tokens=6144))
    if not source.strip():
        raise RuntimeError("the model returned nothing — restate the purpose")
    info = validate(source, expected_name=agent_name)
    return {"source": source, **info, "purpose": purpose}


def _strip_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


# ── creating and loading ──────────────────────────────────────────

def _display_path(path: Path) -> str:
    """Repo-relative when GENERATED_DIR sits under ROOT (always true in
    production); absolute otherwise (a test redirected GENERATED_DIR)."""
    try:
        return str(path.relative_to(config.ROOT))
    except ValueError:
        return str(path)


def write_agent(source: str, agent_name: str = "") -> dict:
    """Validate, then write a generated agent to disk. Does not load it."""
    info = validate(source, expected_name=agent_name)
    _ensure_dir()
    path = GENERATED_DIR / f"{info['agent_name']}_agent.py"
    header = (f'# Generated by Mehltani on {_now()}.\n'
              f'# Reviewed by the factory validator; edit or delete freely.\n')
    path.write_text(header + source if not source.startswith("#") else source)
    display_path = _display_path(path)
    guardian.audit("agent_create", True, reason=f"generated {info['agent_name']}",
                   detail={"path": display_path, "tools": info["tools"]})
    return {**info, "path": display_path}


def load_agent(agent_name: str) -> BaseAgent:
    """Import a generated module from its real path and instantiate the agent."""
    path = GENERATED_DIR / f"{agent_name}_agent.py"
    if not path.exists():
        raise FileNotFoundError(f"no generated agent named {agent_name!r}")

    module_name = f"server.agents.generated.{agent_name}_agent"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so relative imports inside the module resolve.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    for value in vars(module).values():
        if (isinstance(value, type) and issubclass(value, BaseAgent)
                and value is not BaseAgent):
            return value()
    raise ImportError(f"{path.name} defines no BaseAgent subclass")


def load_all() -> dict[str, BaseAgent]:
    """Every generated agent that still loads cleanly.

    A broken generated agent is skipped with a warning rather than taking the
    whole server down — one bad experiment should not cost you the assistant.
    """
    agents: dict[str, BaseAgent] = {}
    if not GENERATED_DIR.exists():
        return agents
    for path in sorted(GENERATED_DIR.glob("*_agent.py")):
        agent_name = path.stem.removesuffix("_agent")
        try:
            agent = load_agent(agent_name)
            agents[agent.name] = agent
        except Exception as exc:
            log.warning("generated agent %s failed to load: %s: %s",
                        agent_name, type(exc).__name__, exc)
            guardian.raise_threat("generated_agent_broken",
                                  f"{path.name} failed to load: {type(exc).__name__}",
                                  severity="info", detail={"error": str(exc)[:400]})
    return agents


def list_generated() -> list[dict]:
    if not GENERATED_DIR.exists():
        return []
    out = []
    for path in sorted(GENERATED_DIR.glob("*_agent.py")):
        source = path.read_text()
        try:
            info = validate(source)
            out.append({"name": info["agent_name"], "tools": info["tools"],
                        "file": path.name, "bytes": len(source),
                        "created": datetime.fromtimestamp(
                            path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
        except Rejected as exc:
            out.append({"name": path.stem.removesuffix("_agent"), "file": path.name,
                        "invalid": str(exc)})
    return out


def remove(agent_name: str, *, presence_token: str = "", recovery_key: str = "") -> dict:
    """Delete a generated agent. Gated — removing a specialist is destructive."""
    guardian.require("agent_disable", presence_token=presence_token,
                     recovery_key=recovery_key, detail={"agent": agent_name})
    path = GENERATED_DIR / f"{agent_name}_agent.py"
    if not path.exists():
        return {"error": f"no generated agent named {agent_name!r}"}
    path.unlink()
    sys.modules.pop(f"server.agents.generated.{agent_name}_agent", None)
    return {"removed": agent_name}


def source_of(agent_name: str) -> str:
    path = GENERATED_DIR / f"{agent_name}_agent.py"
    return path.read_text() if path.exists() else ""
