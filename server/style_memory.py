"""The taste profile — the part of Mehltani that is actually yours.

Everything else in this repo is replaceable. This is not: it is the accumulated
record of what you approved, what you passed on, and the reasons you gave. It is
what makes scouting on day ninety better than scouting on day one.

Design notes:

- One SQLite file next to the ledger. No cloud, no account, no vendor.
- Verdicts are the training signal. Every approve/pass/edit from WhatsApp or the
  voice channel lands here with its attributes, so preferences are *derived*
  rather than declared. People are unreliable narrators of their own taste; what
  they actually pick is the truth.
- Attributes are free-text tags rather than a fixed enum on purpose. Fashion
  vocabulary moves faster than a schema migration, and the model generates the
  tags. A closed taxonomy would quietly discard exactly the emerging signal a
  trend scout exists to catch.
- Scoring is deliberately simple and inspectable (counts + recency weight), not
  an opaque embedding. When Mehltani says "you don't wear cropped", you can open
  the table and see the eleven verdicts that taught him that.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# A verdict from 180 days ago counts about half as much as one from today.
HALF_LIFE_DAYS = 180.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS verdicts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',      -- what was judged
    kind        TEXT NOT NULL DEFAULT 'look',  -- look|garment|hair|makeup|palette|location
    verdict     TEXT NOT NULL,                 -- love|like|pass|hate
    reason      TEXT NOT NULL DEFAULT '',
    attributes  TEXT NOT NULL DEFAULT '[]',    -- JSON array of tags
    source      TEXT NOT NULL DEFAULT 'voice', -- voice|whatsapp|glasses|web
    image_id    TEXT NOT NULL DEFAULT '',
    price       REAL,
    url         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS traits (
    key        TEXT PRIMARY KEY,              -- e.g. "silhouette:oversized"
    note       TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,    -- 1 = stated outright, never decayed
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lookbook (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    brief       TEXT NOT NULL DEFAULT '',
    client      TEXT NOT NULL DEFAULT '',
    occasion    TEXT NOT NULL DEFAULT '',
    pieces      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    hair        TEXT NOT NULL DEFAULT '',
    makeup      TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT '',
    image_ids   TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'draft' -- draft|approved|shot|archived
);

CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    name        TEXT NOT NULL UNIQUE,
    pronouns    TEXT NOT NULL DEFAULT '',
    measurements TEXT NOT NULL DEFAULT '{}',  -- JSON
    colouring   TEXT NOT NULL DEFAULT '',     -- undertone, hair, eyes
    hair_type   TEXT NOT NULL DEFAULT '',
    allergies   TEXT NOT NULL DEFAULT '',
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS scouted (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    brand       TEXT NOT NULL DEFAULT '',
    price       REAL,
    currency    TEXT NOT NULL DEFAULT 'USD',
    url         TEXT NOT NULL DEFAULT '',
    image_url   TEXT NOT NULL DEFAULT '',
    why         TEXT NOT NULL DEFAULT '',
    attributes  TEXT NOT NULL DEFAULT '[]',
    authenticity TEXT NOT NULL DEFAULT '{}',
    state       TEXT NOT NULL DEFAULT 'new',  -- new|sent|loved|passed|bought
    sent_at     TEXT NOT NULL DEFAULT '',
    decided_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_verdicts_created ON verdicts(created_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_verdict ON verdicts(verdict);
CREATE INDEX IF NOT EXISTS idx_lookbook_status  ON lookbook(status);
CREATE INDEX IF NOT EXISTS idx_scouted_state    ON scouted(state);
"""

# Weight per verdict. Negative verdicts are weighted slightly harder than
# positive ones: in styling, a hard "no" is a more reliable signal than a
# polite "sure" — people approve loosely and reject precisely.
VERDICT_WEIGHT = {"love": 2.0, "like": 1.0, "pass": -1.5, "hate": -2.5}


def db_path() -> Path:
    return Path(config.DATA_DIR) / "style.db"


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


def _tags(value: Any) -> list[str]:
    """Normalise attributes from a model, a form, or a JSON string.

    Models are inconsistent about whether they send a list or a comma string,
    so accept both rather than losing the signal to a type error.
    """
    if isinstance(value, str):
        value = [p for p in value.replace("|", ",").split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for tag in value:
        tag = str(tag).strip().lower()
        if tag and tag not in out:
            out.append(tag[:60])
    return out[:24]


# ── verdicts ──────────────────────────────────────────────────────

def record_verdict(subject: str, verdict: str, *, kind: str = "look", reason: str = "",
                   attributes: Any = None, source: str = "voice", image_id: str = "",
                   price: float | None = None, url: str = "") -> dict:
    """Log one judgement. This is the only way taste enters the system."""
    verdict = (verdict or "").strip().lower()
    if verdict in ("yes", "approve", "approved", "buy", "keep"):
        verdict = "love"
    elif verdict in ("no", "reject", "rejected", "skip"):
        verdict = "pass"
    if verdict not in VERDICT_WEIGHT:
        raise ValueError(f"verdict must be one of {sorted(VERDICT_WEIGHT)}, got {verdict!r}")

    conn = connect()
    tags = _tags(attributes)
    cur = conn.execute(
        "INSERT INTO verdicts (created_at, subject, kind, verdict, reason, attributes,"
        " source, image_id, price, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (_now(), subject.strip()[:400], kind.strip().lower() or "look", verdict,
         reason.strip()[:600], json.dumps(tags), source, image_id,
         float(price) if price not in (None, "") else None, url.strip()[:600]))
    conn.commit()
    return {"id": cur.lastrowid, "subject": subject, "verdict": verdict,
            "attributes": tags, "recorded_at": _now()}


def list_verdicts(limit: int = 50, verdict: str = "") -> list[dict]:
    conn = connect()
    sql = "SELECT * FROM verdicts"
    args: list[Any] = []
    if verdict:
        sql += " WHERE verdict = ?"
        args.append(verdict.lower())
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) | {"attributes": json.loads(r["attributes"])}
            for r in conn.execute(sql, args)]


def _recency_weight(created_at: str) -> float:
    """Exponential decay so the profile tracks taste as it moves."""
    try:
        then = datetime.fromisoformat(created_at)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        return 1.0
    days = max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 86400.0)
    return math.pow(0.5, days / HALF_LIFE_DAYS)


def attribute_scores(min_mentions: int = 2) -> list[dict]:
    """Score every attribute the owner has ever reacted to.

    Returns tags sorted by conviction: strongly loved first, strongly rejected
    last. `min_mentions` filters one-off noise — a single mention of "chartreuse"
    is an anecdote, four is a preference.
    """
    tally: dict[str, dict[str, float]] = {}
    for row in connect().execute("SELECT created_at, verdict, attributes FROM verdicts"):
        weight = VERDICT_WEIGHT.get(row["verdict"], 0.0) * _recency_weight(row["created_at"])
        for tag in json.loads(row["attributes"]):
            slot = tally.setdefault(tag, {"score": 0.0, "mentions": 0.0, "positive": 0.0})
            slot["score"] += weight
            slot["mentions"] += 1
            if weight > 0:
                slot["positive"] += 1
    out = [{"attribute": tag, "score": round(v["score"], 2),
            "mentions": int(v["mentions"]),
            "hit_rate": round(v["positive"] / v["mentions"], 2) if v["mentions"] else 0.0}
           for tag, v in tally.items() if v["mentions"] >= min_mentions]
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


# ── stated traits ─────────────────────────────────────────────────

def set_trait(key: str, note: str, pinned: bool = True) -> dict:
    """Record something the owner said outright ("I never wear yellow").

    Pinned traits bypass decay: a declared rule stays true until retracted,
    where an inferred one has to keep earning its place.
    """
    conn = connect()
    conn.execute(
        "INSERT INTO traits (key, note, pinned, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET note=excluded.note, pinned=excluded.pinned,"
        " updated_at=excluded.updated_at",
        (key.strip().lower()[:80], note.strip()[:400], 1 if pinned else 0, _now()))
    conn.commit()
    return {"key": key, "note": note, "pinned": pinned}


def list_traits() -> list[dict]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM traits ORDER BY pinned DESC, updated_at DESC")]


def forget_trait(key: str) -> bool:
    conn = connect()
    cur = conn.execute("DELETE FROM traits WHERE key = ?", (key.strip().lower(),))
    conn.commit()
    return cur.rowcount > 0


# ── lookbook ──────────────────────────────────────────────────────

def add_look(title: str, *, brief: str = "", client: str = "", occasion: str = "",
             pieces: Any = None, hair: str = "", makeup: str = "", notes: str = "",
             image_ids: Any = None, status: str = "draft") -> dict:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO lookbook (created_at, title, brief, client, occasion, pieces,"
        " hair, makeup, notes, image_ids, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (_now(), title.strip()[:200], brief.strip(), client.strip(), occasion.strip(),
         json.dumps(pieces if isinstance(pieces, list) else _tags(pieces)),
         hair.strip(), makeup.strip(), notes.strip(),
         json.dumps(image_ids if isinstance(image_ids, list) else _tags(image_ids)),
         status))
    conn.commit()
    return get_look(cur.lastrowid)


def get_look(look_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM lookbook WHERE id = ?", (look_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["pieces"] = json.loads(out["pieces"])
    out["image_ids"] = json.loads(out["image_ids"])
    return out


def list_looks(status: str = "", limit: int = 25) -> list[dict]:
    sql = "SELECT * FROM lookbook"
    args: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) | {"pieces": json.loads(r["pieces"]),
                       "image_ids": json.loads(r["image_ids"])}
            for r in connect().execute(sql, args)]


def set_look_status(look_id: int, status: str) -> bool:
    conn = connect()
    cur = conn.execute("UPDATE lookbook SET status = ? WHERE id = ?",
                       (status.strip().lower(), look_id))
    conn.commit()
    return cur.rowcount > 0


# ── clients ───────────────────────────────────────────────────────

def upsert_client(name: str, **fields: Any) -> dict:
    """Clients are keyed by name — the way a stylist actually refers to them."""
    conn = connect()
    measurements = fields.get("measurements")
    if isinstance(measurements, dict):
        fields["measurements"] = json.dumps(measurements)
    columns = ("pronouns", "measurements", "colouring", "hair_type", "allergies", "notes")
    existing = conn.execute("SELECT * FROM clients WHERE name = ?", (name.strip(),)).fetchone()
    if existing:
        merged = {c: str(fields.get(c) or existing[c] or "") for c in columns}
        conn.execute(
            "UPDATE clients SET pronouns=?, measurements=?, colouring=?, hair_type=?,"
            " allergies=?, notes=? WHERE name=?",
            (*[merged[c] for c in columns], name.strip()))
    else:
        conn.execute(
            "INSERT INTO clients (created_at, name, pronouns, measurements, colouring,"
            " hair_type, allergies, notes) VALUES (?,?,?,?,?,?,?,?)",
            (_now(), name.strip(), *[str(fields.get(c) or "") for c in columns]))
    conn.commit()
    return get_client(name) or {}


def get_client(name: str) -> dict | None:
    row = connect().execute("SELECT * FROM clients WHERE name = ?",
                            (name.strip(),)).fetchone()
    return dict(row) if row else None


def list_clients() -> list[dict]:
    return [dict(r) for r in connect().execute("SELECT * FROM clients ORDER BY name")]


# ── scouted queue ─────────────────────────────────────────────────

def add_scouted(title: str, *, brand: str = "", price: float | None = None,
                currency: str = "USD", url: str = "", image_url: str = "",
                why: str = "", attributes: Any = None,
                authenticity: dict | None = None) -> dict:
    """Queue a piece the trend agent found, awaiting a verdict."""
    conn = connect()
    cur = conn.execute(
        "INSERT INTO scouted (created_at, title, brand, price, currency, url,"
        " image_url, why, attributes, authenticity) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (_now(), title.strip()[:300], brand.strip()[:120],
         float(price) if price not in (None, "") else None, currency or "USD",
         url.strip()[:800], image_url.strip()[:800], why.strip()[:800],
         json.dumps(_tags(attributes)), json.dumps(authenticity or {})))
    conn.commit()
    return get_scouted(cur.lastrowid) or {}


def get_scouted(scouted_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM scouted WHERE id = ?", (scouted_id,)).fetchone()
    if row is None:
        return None
    return dict(row) | {"attributes": json.loads(row["attributes"]),
                        "authenticity": json.loads(row["authenticity"])}


def list_scouted(state: str = "", limit: int = 25) -> list[dict]:
    sql = "SELECT * FROM scouted"
    args: list[Any] = []
    if state:
        sql += " WHERE state = ?"
        args.append(state)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) | {"attributes": json.loads(r["attributes"]),
                       "authenticity": json.loads(r["authenticity"])}
            for r in connect().execute(sql, args)]


def set_scouted_authenticity(scouted_id: int, assessment: dict) -> bool:
    conn = connect()
    cur = conn.execute("UPDATE scouted SET authenticity = ? WHERE id = ?",
                       (json.dumps(assessment or {}, default=str)[:4000], scouted_id))
    conn.commit()
    return cur.rowcount > 0


def set_scouted_state(scouted_id: int, state: str) -> bool:
    conn = connect()
    column = "sent_at" if state == "sent" else "decided_at"
    cur = conn.execute(f"UPDATE scouted SET state = ?, {column} = ? WHERE id = ?",
                       (state, _now(), scouted_id))
    conn.commit()
    return cur.rowcount > 0


# ── the summary that goes into every prompt ───────────────────────

def summary(max_attributes: int = 18) -> str:
    """A compact, human-readable read of the profile for the system prompt.

    Kept terse deliberately: this is prepended to every single turn, so verbosity
    here is a tax on the whole system.
    """
    lines: list[str] = []

    pinned = [t for t in list_traits() if t["pinned"]]
    if pinned:
        lines.append("Stated rules: " + "; ".join(
            f"{t['key']} — {t['note']}" if t["note"] else t["key"] for t in pinned[:12]))

    scores = attribute_scores()
    loved = [s for s in scores if s["score"] > 0][:max_attributes]
    passed = [s for s in reversed(scores) if s["score"] < 0][:max_attributes]
    if loved:
        lines.append("Gravitates toward: " + ", ".join(
            f"{s['attribute']} ({s['score']:+g})" for s in loved))
    if passed:
        lines.append("Consistently rejects: " + ", ".join(
            f"{s['attribute']} ({s['score']:+g})" for s in passed))

    recent = list_verdicts(limit=6)
    if recent:
        lines.append("Most recent calls: " + "; ".join(
            f"{r['verdict']} on {r['subject'][:60]}" + (f" ({r['reason'][:70]})"
                                                        if r["reason"] else "")
            for r in recent))

    counts = connect().execute(
        "SELECT verdict, COUNT(*) n FROM verdicts GROUP BY verdict").fetchall()
    if counts:
        lines.append("Sample size: " + ", ".join(f"{r['n']} {r['verdict']}" for r in counts))

    if not lines:
        return ("No taste profile yet — nothing has been judged. Ask what they are "
                "drawn to, or scout something and get a first verdict.")
    return "\n".join(lines)


def stats() -> dict:
    conn = connect()
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "verdicts": one("SELECT COUNT(*) FROM verdicts"),
        "traits": one("SELECT COUNT(*) FROM traits"),
        "looks": one("SELECT COUNT(*) FROM lookbook"),
        "clients": one("SELECT COUNT(*) FROM clients"),
        "attributes_learned": len(attribute_scores()),
    }
