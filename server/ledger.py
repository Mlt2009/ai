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

# Reentrant: helpers below call connect() (which locks) from inside locked
# blocks. A plain Lock deadlocks the whole server the first time that happens.
_lock = threading.RLock()
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

CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    number       TEXT NOT NULL UNIQUE,
    customer     TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    address      TEXT NOT NULL DEFAULT '',
    issued_on    TEXT NOT NULL DEFAULT '',
    due_on       TEXT NOT NULL DEFAULT '',
    subtotal     REAL NOT NULL DEFAULT 0,
    tax_rate     REAL NOT NULL DEFAULT 0,
    tax          REAL NOT NULL DEFAULT 0,
    total        REAL NOT NULL DEFAULT 0,
    currency     TEXT NOT NULL DEFAULT 'USD',
    paid         INTEGER NOT NULL DEFAULT 0,
    paid_on      TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    items_json   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS trips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    driven_on  TEXT NOT NULL,
    purpose    TEXT NOT NULL DEFAULT '',
    start_at   TEXT NOT NULL DEFAULT '',
    end_at     TEXT NOT NULL DEFAULT '',
    miles      REAL NOT NULL DEFAULT 0,
    rate       REAL NOT NULL DEFAULT 0,
    deduction  REAL NOT NULL DEFAULT 0,
    vehicle    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title      TEXT NOT NULL,
    customer   TEXT NOT NULL DEFAULT '',
    starts_at  TEXT NOT NULL,
    ends_at    TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(purchased_on);
CREATE INDEX IF NOT EXISTS idx_receipts_cat  ON receipts(category);
CREATE INDEX IF NOT EXISTS idx_invoices_paid ON invoices(paid);
CREATE INDEX IF NOT EXISTS idx_trips_date    ON trips(driven_on);
CREATE INDEX IF NOT EXISTS idx_jobs_start    ON jobs(starts_at);
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


# ── invoices ──────────────────────────────────────────────────────

def next_invoice_number(year: str = "") -> str:
    """Sequential per year: 2026-0001, 2026-0002, …"""
    year = year or date.today().strftime("%Y")
    row = connect().execute(
        "SELECT number FROM invoices WHERE number LIKE ? ORDER BY number DESC LIMIT 1",
        (f"{year}-%",)).fetchone()
    nth = int(row["number"].split("-")[-1]) + 1 if row else 1
    return f"{year}-{nth:04d}"


def add_invoice(customer: str, items: Iterable[dict] | None = None, email: str = "",
                address: str = "", issued_on: str = "", due_on: str = "",
                tax_rate: Any = 0, currency: str = "USD", note: str = "",
                number: str = "") -> dict:
    """Create an invoice; totals are computed from the line items."""
    items = [{"name": str(i.get("name") or i.get("description") or "item"),
              "qty": str(i.get("qty") or "1"),
              "amount": _money(i.get("amount"))} for i in (items or [])]
    subtotal = round(sum(i["amount"] for i in items), 2)
    # A rate is not currency: _money() rounds to 2 decimals and would flatten
    # 0.0825 to 0.08. Parse it at full precision, and accept either 8.25 or
    # 0.0825 as ways of saying the same thing.
    try:
        rate = float(str(tax_rate).replace("%", "").strip() or 0)
    except ValueError:
        rate = 0.0
    if rate > 1:
        rate = rate / 100
    rate = round(rate, 6)
    tax = round(subtotal * rate, 2)

    conn = connect()
    number = number or next_invoice_number()   # queries the DB — do it unlocked
    with _lock:
        cur = conn.execute(
            """INSERT INTO invoices (created_at, number, customer, email, address,
                   issued_on, due_on, subtotal, tax_rate, tax, total, currency,
                   note, items_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"),
             number, customer.strip(), email.strip(),
             address.strip(), (issued_on or _today()).strip(), due_on.strip(),
             subtotal, rate, tax, round(subtotal + tax, 2), currency or "USD",
             note.strip(), json.dumps(items)))
        conn.commit()
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _inflate(row)


def get_invoice(invoice_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    return _inflate(row) if row else None


def find_invoice(number: str) -> dict | None:
    row = connect().execute("SELECT * FROM invoices WHERE number = ?",
                            (number.strip(),)).fetchone()
    return _inflate(row) if row else None


def list_invoices(unpaid_only: bool = False, customer: str = "", limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM invoices WHERE 1=1"
    args: list[Any] = []
    if unpaid_only:
        sql += " AND paid = 0"
    if customer:
        sql, _ = sql + " AND customer LIKE ?", args.append(f"%{customer.strip()}%")
    sql += " ORDER BY issued_on DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    return [_inflate(r) for r in connect().execute(sql, args).fetchall()]


def mark_invoice_paid(invoice_id: int, paid_on: str = "") -> dict | None:
    conn = connect()
    with _lock:
        conn.execute("UPDATE invoices SET paid = 1, paid_on = ? WHERE id = ?",
                     ((paid_on or _today()).strip(), invoice_id))
        conn.commit()
    return get_invoice(invoice_id)


def outstanding() -> dict:
    """What's still owed, and how much of it is past due."""
    rows = list_invoices(unpaid_only=True, limit=500)
    today = _today()
    overdue = [r for r in rows if r["due_on"] and r["due_on"] < today]
    return {"count": len(rows),
            "total": round(sum(r["total"] for r in rows), 2),
            "overdue_count": len(overdue),
            "overdue_total": round(sum(r["total"] for r in overdue), 2),
            "invoices": [{"id": r["id"], "number": r["number"], "customer": r["customer"],
                          "total": r["total"], "due_on": r["due_on"],
                          "overdue": r in overdue} for r in rows]}


# ── mileage ───────────────────────────────────────────────────────

def add_trip(miles: Any, purpose: str = "", driven_on: str = "", start_at: str = "",
             end_at: str = "", rate: Any = 0, vehicle: str = "") -> dict:
    miles_f, rate_f = _money(miles), float(_money(rate))
    conn = connect()
    with _lock:
        cur = conn.execute(
            """INSERT INTO trips (created_at, driven_on, purpose, start_at, end_at,
                   miles, rate, deduction, vehicle) VALUES (?,?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"), (driven_on or _today()).strip(),
             purpose.strip(), start_at.strip(), end_at.strip(), miles_f, rate_f,
             round(miles_f * rate_f, 2), vehicle.strip()))
        conn.commit()
        row = conn.execute("SELECT * FROM trips WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_trips(since: str = "", until: str = "", limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM trips WHERE 1=1"
    args: list[Any] = []
    if since:
        sql, _ = sql + " AND driven_on >= ?", args.append(since)
    if until:
        sql, _ = sql + " AND driven_on <= ?", args.append(until)
    sql += " ORDER BY driven_on DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 1000)))
    return _rows(connect().execute(sql, args))


def mileage_totals(since: str = "", until: str = "") -> dict:
    rows = list_trips(since=since, until=until, limit=1000)
    return {"trips": len(rows),
            "miles": round(sum(r["miles"] for r in rows), 1),
            "deduction": round(sum(r["deduction"] for r in rows), 2)}


def delete_trip(trip_id: int) -> bool:
    conn = connect()
    with _lock:
        cur = conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()
    return cur.rowcount > 0


# ── jobs / schedule ───────────────────────────────────────────────

def add_job(title: str, starts_at: str, customer: str = "", ends_at: str = "",
            location: str = "", note: str = "") -> dict:
    conn = connect()
    with _lock:
        cur = conn.execute(
            """INSERT INTO jobs (created_at, title, customer, starts_at, ends_at,
                   location, note) VALUES (?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"), title.strip(),
             customer.strip(), starts_at.strip(), ends_at.strip(),
             location.strip(), note.strip()))
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_job(job_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(since: str = "", until: str = "", status: str = "",
              limit: int = 50) -> list[dict]:
    """Jobs in a window. `since`/`until` compare against the ISO start time."""
    sql = "SELECT * FROM jobs WHERE 1=1"
    args: list[Any] = []
    if since:
        sql, _ = sql + " AND starts_at >= ?", args.append(since)
    if until:
        sql, _ = sql + " AND starts_at <= ?", args.append(until)
    if status:
        sql, _ = sql + " AND status = ?", args.append(status.strip().lower())
    sql += " ORDER BY starts_at LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    return _rows(connect().execute(sql, args))


def update_job(job_id: int, **fields) -> dict | None:
    allowed = {"title", "customer", "starts_at", "ends_at", "location", "note", "status"}
    updates = {k: str(v).strip() for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_job(job_id)
    columns = ", ".join(f"{k} = ?" for k in updates)
    conn = connect()
    with _lock:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?",
                     [*updates.values(), job_id])
        conn.commit()
    return get_job(job_id)
