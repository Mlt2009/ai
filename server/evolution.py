"""Evolution — Mehltani editing his own source code, safely.

You asked for something that can rewrite its own code. That is a real capability
and this module implements it for real, but it deliberately does *not* work the
naive way (model emits code, process exec's it). Self-modifying software that
skips verification does not become smarter over time, it becomes broken in ways
nobody can retrace, and the failure is usually silent.

The pipeline instead:

    propose  ->  a full replacement file is written to a proposal record, never
                 to the live tree. Nothing is executing yet.
    verify   ->  the whole repo is copied to a scratch directory, the change is
                 applied *there*, and the test suite runs against the copy in a
                 subprocess. A syntax error or a failing test kills the proposal.
    review   ->  the diff is shown to you, on the dashboard or over WhatsApp.
    apply    ->  gated behind your fingerprint (guardian: evolution_apply). Only
                 now does the live file change, and it lands as a git commit.
    rollback ->  every applied change is a commit, so undoing one is `git revert`.

Two hard limits that are not configurable:

  * `guardian.py` cannot be modified through this pipeline. Code that can edit
    its own safety check has no safety check.
  * The changed process is never hot-patched into the running interpreter. A
    restart is required, so a bad change cannot corrupt a live conversation.
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import brain, config, guardian

log = logging.getLogger("evolution")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# Never editable by Mehltani himself, at any privilege level.
FROZEN = {"server/guardian.py", "server/evolution.py", "server/config.py"}

# Only these trees are in scope. Keeps a well-meaning refactor from wandering
# into the virtualenv or the git objects.
EDITABLE_ROOTS = ("server/", "web/", "tests/", "desktop/")

TEST_TIMEOUT = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    goal        TEXT NOT NULL,
    path        TEXT NOT NULL,
    new_source  TEXT NOT NULL,
    old_source  TEXT NOT NULL DEFAULT '',
    rationale   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'draft',  -- draft|verified|rejected|applied|reverted
    test_output TEXT NOT NULL DEFAULT '',
    commit_sha  TEXT NOT NULL DEFAULT '',
    decided_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
"""


def db_path() -> Path:
    return Path(config.DATA_DIR) / "evolution.db"


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── path safety ───────────────────────────────────────────────────

def check_path(rel_path: str) -> Path:
    """Resolve a repo-relative path, refusing anything out of bounds."""
    rel = rel_path.strip().lstrip("/")
    if rel in FROZEN:
        raise ValueError(f"{rel} is frozen — Mehltani cannot edit his own safety code")
    if not rel.startswith(EDITABLE_ROOTS):
        raise ValueError(f"{rel} is outside the editable roots {EDITABLE_ROOTS}")
    target = (config.ROOT / rel).resolve()
    if not str(target).startswith(str(config.ROOT.resolve()) + os.sep):
        raise ValueError("path escapes the repository")
    if target.suffix not in (".py", ".js", ".css", ".html", ".json", ".md", ".txt"):
        raise ValueError(f"refusing to write {target.suffix or 'extensionless'} files")
    return target


def _syntax_ok(rel_path: str, source: str) -> tuple[bool, str]:
    if not rel_path.endswith(".py"):
        return True, ""
    try:
        ast.parse(source)
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError line {exc.lineno}: {exc.msg}"


# ── proposing ─────────────────────────────────────────────────────

def read_source(rel_path: str) -> str:
    target = check_path(rel_path)
    return target.read_text() if target.exists() else ""


async def propose(goal: str, rel_path: str, *, rationale: str = "",
                  new_source: str = "") -> dict:
    """Draft a change. If no source is supplied, ask the brain to write it.

    The model gets the *entire current file* and must return the *entire new
    file*. Whole-file replacement rather than a patch format is a deliberate
    trade: it costs more tokens but removes a whole class of silent corruption
    where a fuzzy hunk applies at the wrong offset.
    """
    target = check_path(rel_path)
    old_source = target.read_text() if target.exists() else ""

    if not new_source.strip():
        prompt = (
            "You are editing your own source code. Rewrite the file below so that "
            "it achieves the goal. Return ONLY the complete new file contents — no "
            "markdown fence, no commentary, no explanation before or after.\n\n"
            "Preserve the existing style: 4-space indent, double quotes, "
            "`from __future__ import annotations`, docstrings that explain why "
            "rather than what. Keep every existing public function working unless "
            "the goal explicitly says to change it.\n\n"
            f"GOAL: {goal}\n\nFILE: {rel_path}\n\n"
            f"CURRENT CONTENTS:\n{old_source or '(new file)'}\n")
        new_source = _strip_fence(await brain.complete(prompt, max_tokens=8192))

    if not new_source.strip():
        raise RuntimeError("the model returned nothing — try restating the goal")

    ok, detail = _syntax_ok(rel_path, new_source)
    conn = connect()
    cur = conn.execute(
        "INSERT INTO proposals (created_at, goal, path, new_source, old_source,"
        " rationale, status, test_output) VALUES (?,?,?,?,?,?,?,?)",
        (_now(), goal, rel_path, new_source, old_source, rationale,
         "draft" if ok else "rejected", "" if ok else detail))
    conn.commit()
    proposal = get(cur.lastrowid)
    if not ok:
        proposal["error"] = f"proposal rejected: {detail}"
    return proposal


def _strip_fence(text: str) -> str:
    """Models wrap code in ``` even when told not to. Unwrap it."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def diff(proposal_id: int, context: int = 3) -> str:
    row = get(proposal_id)
    if not row:
        return ""
    return "".join(difflib.unified_diff(
        row["old_source"].splitlines(keepends=True),
        row["new_source"].splitlines(keepends=True),
        fromfile=f"a/{row['path']}", tofile=f"b/{row['path']}", n=context))


# ── verifying ─────────────────────────────────────────────────────

def _copy_repo(destination: Path) -> None:
    """Mirror the repo into a scratch dir, skipping what tests never need."""
    ignore = shutil.ignore_patterns(".git", ".venv", "venv", "node_modules",
                                    "__pycache__", "data", "*.pyc", ".pytest_cache")
    shutil.copytree(config.ROOT, destination, ignore=ignore, dirs_exist_ok=True)


async def verify(proposal_id: int) -> dict:
    """Apply the proposal to a throwaway copy and run the suite against it.

    This is the whole reason the pipeline is trustworthy. The live tree is not
    touched, so a proposal that segfaults the interpreter costs nothing.
    """
    row = get(proposal_id)
    if not row:
        return {"error": f"no proposal {proposal_id}"}
    if row["status"] == "applied":
        return {"error": "already applied"}

    ok, detail = _syntax_ok(row["path"], row["new_source"])
    if not ok:
        _set_status(proposal_id, "rejected", test_output=detail)
        return {"proposal_id": proposal_id, "passed": False, "reason": detail}

    with tempfile.TemporaryDirectory(prefix="mehltani-verify-") as scratch:
        sandbox = Path(scratch) / "repo"
        await asyncio.to_thread(_copy_repo, sandbox)
        target = sandbox / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(row["new_source"])

        result = await asyncio.to_thread(_run_tests, sandbox)

    status = "verified" if result["passed"] else "rejected"
    _set_status(proposal_id, status, test_output=result["output"][-8000:])
    guardian.audit("evolution_verify", result["passed"],
                   reason=f"proposal {proposal_id} on {row['path']}",
                   detail={"passed": result["passed"]})
    return {"proposal_id": proposal_id, "passed": result["passed"],
            "status": status, "output": result["output"][-4000:]}


def _run_tests(sandbox: Path) -> dict:
    """Run the suite inside the scratch copy, isolated from real data."""
    env = dict(os.environ)
    env["DATA_DIR"] = str(sandbox / ".verify-data")
    env["PYTHONPATH"] = str(sandbox)
    # The suite this runs includes tests that themselves call evolution.verify()
    # (see tests/test_mehltani.py). Without this flag, that call would run the
    # *entire* suite again in a fresh sandbox — including those same tests —
    # recursing without a base case until the machine runs out of processes or
    # disk. Tests that call verify() check this flag and skip themselves when
    # they are already running inside someone else's sandboxed verification.
    env["MEHLTANI_SANDBOXED_VERIFY"] = "1"
    # Never let a sandboxed test reach the network or the real .env.
    env.pop("GEMINI_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        completed = subprocess.run(
            [os.sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=sandbox, env=env, capture_output=True, text=True, timeout=TEST_TIMEOUT)
        output = (completed.stdout + completed.stderr).strip()
        return {"passed": completed.returncode == 0, "output": output}
    except subprocess.TimeoutExpired:
        return {"passed": False, "output": f"tests exceeded {TEST_TIMEOUT}s — "
                                           "likely an infinite loop in the change"}
    except Exception as exc:
        return {"passed": False, "output": f"{type(exc).__name__}: {exc}"}


# ── applying ──────────────────────────────────────────────────────

def _git(*args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(["git", *args], cwd=config.ROOT,
                                   capture_output=True, text=True, timeout=60)
        return completed.returncode, (completed.stdout + completed.stderr).strip()
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def apply(proposal_id: int, *, presence_token: str = "", recovery_key: str = "") -> dict:
    """Ship a verified proposal to the live tree. Fingerprint required."""
    row = get(proposal_id)
    if not row:
        return {"error": f"no proposal {proposal_id}"}
    if row["status"] != "verified":
        return {"error": f"proposal is {row['status']} — it must pass verify() first"}

    guardian.require("evolution_apply", presence_token=presence_token,
                     recovery_key=recovery_key,
                     detail={"proposal": proposal_id, "path": row["path"]})

    target = check_path(row["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(row["new_source"])

    code, _ = _git("add", row["path"])
    sha = ""
    if code == 0:
        message = (f"evolve: {row['goal'][:68]}\n\n"
                   f"Proposal #{proposal_id}, verified against the test suite before "
                   f"apply.\n{row['rationale'][:500]}")
        code, out = _git("commit", "-m", message, "--no-verify")
        if code == 0:
            _, sha = _git("rev-parse", "HEAD")
        else:
            log.warning("git commit failed after apply: %s", out)

    _set_status(proposal_id, "applied", commit_sha=sha[:40])
    return {"proposal_id": proposal_id, "path": row["path"], "status": "applied",
            "commit": sha[:12],
            "note": "restart Mehltani for the change to take effect — a running "
                    "process keeps the old code in memory on purpose"}


def rollback(proposal_id: int, *, presence_token: str = "",
             recovery_key: str = "") -> dict:
    """Undo an applied change by restoring the file it replaced."""
    row = get(proposal_id)
    if not row:
        return {"error": f"no proposal {proposal_id}"}
    if row["status"] != "applied":
        return {"error": f"proposal is {row['status']}, nothing to roll back"}

    guardian.require("evolution_apply", presence_token=presence_token,
                     recovery_key=recovery_key,
                     detail={"rollback_of": proposal_id})

    target = check_path(row["path"])
    if row["old_source"]:
        target.write_text(row["old_source"])
    elif target.exists():
        target.unlink()  # the proposal created this file; undo means remove it

    _git("add", row["path"])
    _git("commit", "-m", f"revert: roll back proposal #{proposal_id}", "--no-verify")
    _set_status(proposal_id, "reverted")
    return {"proposal_id": proposal_id, "status": "reverted", "path": row["path"],
            "note": "restart Mehltani to load the restored code"}


def reject(proposal_id: int, reason: str = "") -> dict:
    _set_status(proposal_id, "rejected", test_output=reason)
    return {"proposal_id": proposal_id, "status": "rejected", "reason": reason}


# ── records ───────────────────────────────────────────────────────

def _set_status(proposal_id: int, status: str, *, test_output: str | None = None,
                commit_sha: str = "") -> None:
    conn = connect()
    fields = ["status = ?", "decided_at = ?"]
    args: list[Any] = [status, _now()]
    if test_output is not None:
        fields.append("test_output = ?")
        args.append(test_output)
    if commit_sha:
        fields.append("commit_sha = ?")
        args.append(commit_sha)
    args.append(proposal_id)
    conn.execute(f"UPDATE proposals SET {', '.join(fields)} WHERE id = ?", args)
    conn.commit()


def get(proposal_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM proposals WHERE id = ?",
                            (proposal_id,)).fetchone()
    return dict(row) if row else None


def history(limit: int = 20, status: str = "") -> list[dict]:
    sql = "SELECT id, created_at, goal, path, status, commit_sha, decided_at FROM proposals"
    args: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in connect().execute(sql, args)]


def stats() -> dict:
    conn = connect()
    by_status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) n FROM proposals GROUP BY status")}
    return {"total": sum(by_status.values()), "by_status": by_status,
            "frozen_files": sorted(FROZEN), "editable_roots": list(EDITABLE_ROOTS)}
