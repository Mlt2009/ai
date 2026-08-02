"""Ledger — the workspace's SQLite store for receipts, shopping and budgets.

Everything the Finance, Shopping and Scan agents remember lives here. One
file on your own machine (DATA_DIR/ledger.db), no cloud, no account.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    merchant       TEXT NOT NULL DEFAULT '',
    purchased_on   TEXT NOT NULL DEFAULT '',
    subtotal       REAL NOT NULL DEFAULT 0,
    tax            REAL NOT NULL DEFAULT 0,
    total          REAL NOT NULL DEFAULT 0,
    currency       TEXT NOT NULL DEFAULT 'USD',
    category       TEXT NOT NULL DEFAULT 'uncategorized',
    payment_method TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    items_json     TEXT NOT NULL DEFAULT '[]',
    raw_text       TEXT NOT NULL DEFAULT '',
    image_id       TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS shopping_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name       TEXT NOT NULL,
    qty        TEXT NOT NULL DEFAULT '1',
    store      TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    done       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS budgets (
    category     TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(purchased_on);
CREATE INDEX IF NOT EXISTS idx_receipts_cat  ON receipts(category);
"""


def db_path() -> Path:
    return Path(config.DATA_DIR) / "ledger.db"


def connect() -> sqlite3.Connection:
    """Open (once) the shared connection and make sure the schema exists."""
    global _conn
    with _lock:
        if _conn is None:
            db_path().parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(db_path(), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def close() -> None:
    """Release the connection (tests call this; the server never needs to)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _money(value: Any) -> float:
    """Coerce '$1,234.56' / '1234.56' / None into a float, never raising."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):  # (12.34) = -12.34
        cleaned = "-" + cleaned[1:-1]
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return 0.0


def _today() -> str:
    return date.today().isoformat()


# ── receipts / expenses ───────────────────────────────────────────

def add_receipt(
    merchant: str = "",
    total: Any = 0,
    purchased_on: str = "",
    subtotal: Any = 0,
    tax: Any = 0,
    currency: str = "USD",
    category: str = "uncategorized",
    payment_method: str = "",
    note: str = "",
    items: Iterable[dict] | None = None,
    raw_text: str = "",
    image_id: str = "",
    source: str = "manual",
) -> dict:
    """Insert one receipt/expense and return the stored row."""
    items = list(items or [])
    total_f, subtotal_f, tax_f = _money(total), _money(subtotal), _money(tax)
    # A receipt with only line items still deserves a usable total.
    if not total_f:
        total_f = round(subtotal_f + tax_f, 2) or round(
            sum(_money(i.get("amount")) for i in items), 2)
    if not subtotal_f:
        subtotal_f = round(total_f - tax_f, 2)

    conn = connect()
    with _lock:
        cur = conn.execute(
            """INSERT INTO receipts (created_at, merchant, purchased_on, subtotal, tax,
                   total, currency, category, payment_method, note, items_json,
                   raw_text, image_id, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"), merchant.strip(),
             (purchased_on or _today()).strip(), subtotal_f, tax_f, total_f,
             currency or "USD", (category or "uncategorized").strip().lower(),
             payment_method.strip(), note.strip(), json.dumps(items),
             raw_text, image_id, source),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM receipts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _inflate(row)


def get_receipt(receipt_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    return _inflate(row) if row else None


def _inflate(row: sqlite3.Row) -> dict:
    out = dict(row)
    try:
        out["items"] = json.loads(out.pop("items_json") or "[]")
    except json.JSONDecodeError:
        out["items"] = []
    return out


def list_receipts(since: str = "", until: str = "", category: str = "",
                  merchant: str = "", limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM receipts WHERE 1=1"
    args: list[Any] = []
    if since:
        sql, _ = sql + " AND purchased_on >= ?", args.append(since)
    if until:
        sql, _ = sql + " AND purchased_on <= ?", args.append(until)
    if category:
        sql, _ = sql + " AND category = ?", args.append(category.strip().lower())
    if merchant:
        sql, _ = sql + " AND merchant LIKE ?", args.append(f"%{merchant.strip()}%")
    sql += " ORDER BY purchased_on DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    return [_inflate(r) for r in connect().execute(sql, args).fetchall()]


def delete_receipt(receipt_id: int) -> bool:
    conn = connect()
    with _lock:
        cur = conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        conn.commit()
    return cur.rowcount > 0


def totals(group_by: str = "category", since: str = "", until: str = "") -> list[dict]:
    """Spend totals grouped by category, merchant or month."""
    column = {
        "category": "category",
        "merchant": "merchant",
        "month": "substr(purchased_on, 1, 7)",
    }.get(group_by, "category")
    sql = f"SELECT {column} AS group_key, COUNT(*) AS count, ROUND(SUM(total), 2) AS total " \
          "FROM receipts WHERE 1=1"
    args: list[Any] = []
    if since:
        sql, _ = sql + " AND purchased_on >= ?", args.append(since)
    if until:
        sql, _ = sql + " AND purchased_on <= ?", args.append(until)
    sql += " GROUP BY group_key ORDER BY total DESC"
    return _rows(connect().execute(sql, args))


# ── shopping list ─────────────────────────────────────────────────

def add_item(name: str, qty: str = "1", store: str = "", note: str = "") -> dict:
    conn = connect()
    with _lock:
        cur = conn.execute(
            "INSERT INTO shopping_items (created_at, name, qty, store, note) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), name.strip(),
             str(qty).strip() or "1", store.strip(), note.strip()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM shopping_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_items(store: str = "", include_done: bool = False) -> list[dict]:
    sql = "SELECT * FROM shopping_items WHERE 1=1"
    args: list[Any] = []
    if not include_done:
        sql += " AND done = 0"
    if store:
        sql, _ = sql + " AND store = ?", args.append(store.strip())
    sql += " ORDER BY store, id"
    return _rows(connect().execute(sql, args))


def check_off(name: str) -> int:
    """Mark every open item whose name matches (case-insensitive) as done."""
    conn = connect()
    with _lock:
        cur = conn.execute(
            "UPDATE shopping_items SET done = 1 WHERE done = 0 AND lower(name) LIKE lower(?)",
            (f"%{name.strip()}%",),
        )
        conn.commit()
    return cur.rowcount


def clear_items(done_only: bool = True) -> int:
    conn = connect()
    with _lock:
        cur = conn.execute(
            "DELETE FROM shopping_items" + (" WHERE done = 1" if done_only else ""))
        conn.commit()
    return cur.rowcount


# ── budgets ───────────────────────────────────────────────────────

def set_budget(category: str, monthly_limit: float) -> dict:
    conn = connect()
    with _lock:
        conn.execute(
            "INSERT INTO budgets (category, monthly_limit) VALUES (?,?) "
            "ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit",
            (category.strip().lower(), _money(monthly_limit)),
        )
        conn.commit()
    return {"category": category.strip().lower(), "monthly_limit": _money(monthly_limit)}


def budget_status(month: str = "") -> list[dict]:
    """Per-category spend vs limit for a month (YYYY-MM, defaults to now)."""
    month = month or date.today().strftime("%Y-%m")
    spent = {r["group_key"]: r["total"] for r in
             totals("category", since=f"{month}-01", until=f"{month}-31")}
    out = []
    for row in connect().execute("SELECT * FROM budgets ORDER BY category").fetchall():
        used = spent.pop(row["category"], 0.0) or 0.0
        out.append({
            "category": row["category"],
            "monthly_limit": row["monthly_limit"],
            "spent": round(used, 2),
            "remaining": round(row["monthly_limit"] - used, 2),
            "over_budget": used > row["monthly_limit"],
        })
    # Categories with spend but no budget set still matter to the user.
    for category, used in spent.items():
        out.append({"category": category, "monthly_limit": None,
                    "spent": round(used or 0.0, 2), "remaining": None, "over_budget": False})
    return out
