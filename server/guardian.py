"""Guardian — biometric-gated controls, an audit trail, and a threat monitor.

WHAT "FINGER ACCESS" ACTUALLY MEANS HERE
----------------------------------------
You asked that Mehltani not be shut down without your fingerprint. Implemented
literally that is a bad idea and it is also impossible: any process on a machine
you own can be killed by the operating system, and software that fights its
owner's kill signal is malware by definition, not a feature.

So here is what this module really does, which is the thing you actually want:

  * Every control that matters — stopping Mehltani, disabling an agent, changing
    settings, unlocking the shell, approving a code change, spending money — is
    gated behind a real biometric check (WebAuthn platform authenticator: Touch
    ID, Face ID, Windows Hello, Android fingerprint).
  * That gate stops *other people*. Someone who steals your phone with the app
    open, or reaches the dashboard over your network, cannot turn Mehltani off,
    read your keys, or approve a purchase. They will fail at the fingerprint.
  * It never stops *you*. `Ctrl-C` in the terminal, `kill`, closing the laptop —
    all still work, always, by design. There is also a documented local escape
    hatch below for the case where your enrolled device is lost or broken.
  * Uptime comes from supervision, not from resisting shutdown: run under the
    watchdog and a crash restarts automatically. That is the honest way to get
    "always on".

Everything sensitive lands in the audit table whether it succeeded or not, so
there is a record of who asked for what.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("guardian")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# Pending WebAuthn challenges and granted presence tokens. In-memory on purpose:
# a restart should invalidate every session, and neither survives a crash.
_challenges: dict[str, dict] = {}
_presence: dict[str, dict] = {}

CHALLENGE_TTL = 120           # seconds to complete a fingerprint prompt
PRESENCE_TTL = 300            # a successful check authorises 5 minutes of work
MAX_FAILED_BEFORE_ALERT = 5   # failed checks in the window before we raise a threat
FAIL_WINDOW = 600

# Operations that require a live fingerprint. Everything not listed runs freely —
# Mehltani is meant to be useful without nagging, so the gate is reserved for
# things that are irreversible, expensive, or that weaken the system itself.
PROTECTED_OPS = {
    "shutdown":        "stop or restart Mehltani",
    "settings_write":  "change settings or API keys",
    "reveal_secret":   "reveal a stored credential",
    "agent_disable":   "disable or remove a subagent",
    "shell_unlock":    "turn on shell access",
    "evolution_apply": "ship a change to Mehltani's own code",
    "purchase":        "spend money",
    "send_external":   "email or message someone outside the household",
    "file_delete":     "delete files outside the sandbox",
    "lockdown_clear":  "clear lockdown mode",
    "credential_add":  "enrol a new fingerprint device",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
    id            TEXT PRIMARY KEY,           -- base64url credential id
    created_at    TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    public_key    TEXT NOT NULL,              -- base64 COSE key
    sign_count    INTEGER NOT NULL DEFAULT 0,
    transports    TEXT NOT NULL DEFAULT '[]',
    last_used_at  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    op         TEXT NOT NULL,
    actor      TEXT NOT NULL DEFAULT '',
    allowed    INTEGER NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS threats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    severity   TEXT NOT NULL DEFAULT 'info',  -- info|warn|critical
    kind       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '{}',
    resolved   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS baseline (
    path   TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_at   ON audit(at);
CREATE INDEX IF NOT EXISTS idx_threats_at ON threats(at);
"""


def db_path() -> Path:
    return Path(config.DATA_DIR) / "guardian.db"


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


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── audit ─────────────────────────────────────────────────────────

def audit(op: str, allowed: bool, *, actor: str = "", reason: str = "",
          detail: dict | None = None) -> None:
    conn = connect()
    conn.execute("INSERT INTO audit (at, op, actor, allowed, reason, detail) VALUES (?,?,?,?,?,?)",
                 (_now(), op, actor, 1 if allowed else 0, reason,
                  json.dumps(detail or {}, default=str)[:4000]))
    conn.commit()
    (log.info if allowed else log.warning)("audit %s %s (%s)", op,
                                           "allowed" if allowed else "DENIED", reason)


def audit_log(limit: int = 50, only_denied: bool = False) -> list[dict]:
    sql = "SELECT * FROM audit"
    if only_denied:
        sql += " WHERE allowed = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    return [dict(r) | {"detail": json.loads(r["detail"])}
            for r in connect().execute(sql, (int(limit),))]


# ── threats ───────────────────────────────────────────────────────

def raise_threat(kind: str, summary_text: str, severity: str = "warn",
                 detail: dict | None = None) -> dict:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO threats (at, severity, kind, summary, detail) VALUES (?,?,?,?,?)",
        (_now(), severity, kind, summary_text, json.dumps(detail or {}, default=str)[:4000]))
    conn.commit()
    log.warning("threat [%s] %s: %s", severity, kind, summary_text)
    if severity == "critical" and config.AUTO_LOCKDOWN:
        engage_lockdown(f"critical threat: {kind}")
    return {"id": cur.lastrowid, "kind": kind, "severity": severity,
            "summary": summary_text}


def threat_log(limit: int = 40, unresolved_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM threats"
    if unresolved_only:
        sql += " WHERE resolved = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    return [dict(r) | {"detail": json.loads(r["detail"])}
            for r in connect().execute(sql, (int(limit),))]


def resolve_threat(threat_id: int) -> bool:
    conn = connect()
    cur = conn.execute("UPDATE threats SET resolved = 1 WHERE id = ?", (threat_id,))
    conn.commit()
    return cur.rowcount > 0


# ── lockdown ──────────────────────────────────────────────────────

_lockdown: dict[str, Any] = {"on": False, "since": "", "reason": ""}


def engage_lockdown(reason: str) -> dict:
    """Refuse every protected operation until a fingerprint clears it.

    Deliberately does not stop ordinary conversation — locking you out of your
    own assistant because a port scan looked odd would be worse than the threat.
    """
    _lockdown.update({"on": True, "since": _now(), "reason": reason})
    audit("lockdown_engage", True, reason=reason)
    return dict(_lockdown)


def clear_lockdown() -> dict:
    _lockdown.update({"on": False, "since": "", "reason": ""})
    return dict(_lockdown)


def lockdown_state() -> dict:
    return dict(_lockdown)


# ── WebAuthn: enrolling a finger ──────────────────────────────────

def _webauthn():
    """Import py_webauthn lazily so the server still boots without it."""
    try:
        import webauthn  # type: ignore
        from webauthn.helpers import structs  # noqa: F401
        return webauthn
    except ImportError:
        return None


def biometrics_available() -> tuple[bool, str]:
    if _webauthn() is None:
        return False, "the `webauthn` package is not installed (pip install -r requirements.txt)"
    if not config.RP_ID:
        return False, "RP_ID is not set — see .env.example"
    return True, "ready"


def credentials() -> list[dict]:
    return [{"id": r["id"], "label": r["label"], "created_at": r["created_at"],
             "last_used_at": r["last_used_at"]}
            for r in connect().execute("SELECT * FROM credentials ORDER BY created_at")]


def enrolled() -> bool:
    return connect().execute("SELECT COUNT(*) FROM credentials").fetchone()[0] > 0


def begin_registration(label: str = "my device") -> dict:
    """Options for navigator.credentials.create() — the enrol-a-finger prompt."""
    wa = _webauthn()
    if wa is None:
        raise RuntimeError("webauthn package not installed")
    from webauthn.helpers.structs import (AuthenticatorAttachment,
                                          AuthenticatorSelectionCriteria,
                                          ResidentKeyRequirement,
                                          UserVerificationRequirement)

    challenge = secrets.token_bytes(32)
    options = wa.generate_registration_options(
        rp_id=config.RP_ID,
        rp_name="Mehltani",
        user_id=b"owner",
        user_name=config.OWNER_NAME or "owner",
        user_display_name=config.OWNER_NAME or "Owner",
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # platform = the fingerprint reader built into this phone/laptop,
            # rather than a roaming USB key. That is what "finger access" means.
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    state = secrets.token_urlsafe(16)
    _challenges[state] = {"challenge": challenge, "kind": "register",
                          "label": label, "expires": time.time() + CHALLENGE_TTL}
    return {"state": state, "options": json.loads(wa.options_to_json(options))}


def finish_registration(state: str, credential: dict, *, presence_token: str = "",
                        recovery_key: str = "") -> dict:
    """Complete an enrolment. Adding a device beyond the first one is gated.

    The very first-ever enrolment is the one necessary exception: nothing could
    confirm it, since nothing is enrolled yet. Every enrolment after that must
    prove presence of an *existing* device first — otherwise anyone who reaches
    this endpoint before the owner enrols a second device could plant a
    permanent fingerprint backdoor with no confirmation from the real owner.
    """
    wa = _webauthn()
    if wa is None:
        raise RuntimeError("webauthn package not installed")
    pending = _take_challenge(state, "register")
    if enrolled():
        require("credential_add", presence_token=presence_token, recovery_key=recovery_key,
               detail={"label": pending.get("label", "")})
    verification = wa.verify_registration_response(
        credential=credential,
        expected_challenge=pending["challenge"],
        expected_rp_id=config.RP_ID,
        expected_origin=config.expected_origins(),
        require_user_verification=True,
    )
    cred_id = _b64(verification.credential_id)
    conn = connect()
    conn.execute(
        "INSERT INTO credentials (id, created_at, label, public_key, sign_count, transports)"
        " VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label",
        (cred_id, _now(), pending["label"],
         base64.b64encode(verification.credential_public_key).decode(),
         verification.sign_count, json.dumps(credential.get("transports") or [])))
    conn.commit()
    audit("credential_add", True, reason=f"enrolled {pending['label']}")
    return {"credential_id": cred_id, "label": pending["label"],
            "total_enrolled": len(credentials())}


def forget_credential(credential_id: str) -> bool:
    """Remove a device. Refuses to remove the last one while a gate is armed.

    Deleting your only enrolled finger would leave protected operations
    permanently unreachable except via the recovery key, which is a footgun
    worth blocking outright.
    """
    if len(credentials()) <= 1:
        raise RuntimeError("that is the only enrolled device — enrol another first, "
                           "otherwise you would lock yourself out")
    conn = connect()
    cur = conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
    conn.commit()
    audit("credential_remove", cur.rowcount > 0, detail={"credential_id": credential_id})
    return cur.rowcount > 0


# ── WebAuthn: proving a finger ────────────────────────────────────

def begin_authentication(op: str = "") -> dict:
    """Options for navigator.credentials.get() — the 'touch to confirm' prompt."""
    wa = _webauthn()
    if wa is None:
        raise RuntimeError("webauthn package not installed")
    from webauthn.helpers.structs import (PublicKeyCredentialDescriptor,
                                          UserVerificationRequirement)

    known = [PublicKeyCredentialDescriptor(id=_unb64(c["id"])) for c in credentials()]
    if not known:
        raise RuntimeError("no fingerprint enrolled yet — enrol a device first")
    challenge = secrets.token_bytes(32)
    options = wa.generate_authentication_options(
        rp_id=config.RP_ID,
        challenge=challenge,
        allow_credentials=known,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    state = secrets.token_urlsafe(16)
    _challenges[state] = {"challenge": challenge, "kind": "auth", "op": op,
                          "expires": time.time() + CHALLENGE_TTL}
    return {"state": state, "op": op, "options": json.loads(wa.options_to_json(options))}


def finish_authentication(state: str, credential: dict) -> dict:
    """Verify the assertion and mint a short-lived presence token."""
    wa = _webauthn()
    if wa is None:
        raise RuntimeError("webauthn package not installed")
    pending = _take_challenge(state, "auth")
    cred_id = credential.get("id") or credential.get("rawId") or ""
    row = connect().execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if row is None:
        _note_failure("unknown credential presented")
        raise RuntimeError("that device is not enrolled")

    try:
        verification = wa.verify_authentication_response(
            credential=credential,
            expected_challenge=pending["challenge"],
            expected_rp_id=config.RP_ID,
            expected_origin=config.expected_origins(),
            credential_public_key=base64.b64decode(row["public_key"]),
            credential_current_sign_count=row["sign_count"],
            require_user_verification=True,
        )
    except Exception as exc:
        _note_failure(f"assertion failed: {type(exc).__name__}")
        raise

    conn = connect()
    conn.execute("UPDATE credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
                 (verification.new_sign_count, _now(), cred_id))
    conn.commit()

    token = secrets.token_urlsafe(32)
    _presence[token] = {"granted": time.time(), "expires": time.time() + PRESENCE_TTL,
                        "credential": cred_id, "op": pending.get("op", "")}
    audit("biometric_verify", True, actor=row["label"], reason=pending.get("op", ""))
    return {"presence_token": token, "expires_in": PRESENCE_TTL,
            "device": row["label"]}


def _take_challenge(state: str, kind: str) -> dict:
    pending = _challenges.pop(state, None)
    if pending is None:
        raise RuntimeError("that prompt expired or was already used — try again")
    if pending["kind"] != kind or pending["expires"] < time.time():
        raise RuntimeError("that prompt expired — try again")
    return pending


_failures: list[float] = []


def _note_failure(reason: str) -> None:
    """Track failed biometric attempts; a burst is an intrusion signal."""
    now = time.time()
    _failures.append(now)
    while _failures and _failures[0] < now - FAIL_WINDOW:
        _failures.pop(0)
    audit("biometric_verify", False, reason=reason)
    if len(_failures) >= MAX_FAILED_BEFORE_ALERT:
        raise_threat("biometric_bruteforce",
                     f"{len(_failures)} failed fingerprint checks in "
                     f"{FAIL_WINDOW // 60} minutes",
                     severity="critical", detail={"latest_reason": reason})


# ── the gate itself ───────────────────────────────────────────────

class Denied(RuntimeError):
    """Raised when a protected operation is attempted without presence."""


def presence_ok(token: str) -> bool:
    entry = _presence.get(token or "")
    if entry is None:
        return False
    if entry["expires"] < time.time():
        _presence.pop(token, None)
        return False
    return True


def recovery_ok(supplied: str) -> bool:
    """The documented escape hatch.

    If your enrolled phone is lost, drowned or bricked, set RECOVERY_KEY in .env
    (on the machine itself — which already implies physical access) and pass it
    instead of a fingerprint. Compared in constant time. This exists because an
    assistant you can be permanently locked out of is a liability, not a vault.
    """
    expected = config.RECOVERY_KEY
    if not expected or not supplied:
        return False
    return secrets.compare_digest(str(supplied), expected)


def require(op: str, *, presence_token: str = "", recovery_key: str = "",
            detail: dict | None = None) -> None:
    """Authorise a protected operation, or raise Denied.

    Order matters: lockdown is checked first so that a compromised session
    cannot spend a still-valid presence token acquired before the alarm.
    """
    if op not in PROTECTED_OPS:
        return  # not a gated operation

    if _lockdown["on"] and op != "lockdown_clear":
        audit(op, False, reason="lockdown active", detail=detail)
        raise Denied(f"Mehltani is in lockdown ({_lockdown['reason']}). "
                     "Clear it with your fingerprint first.")

    if not config.REQUIRE_BIOMETRIC:
        audit(op, True, reason="biometric gate disabled in settings", detail=detail)
        return

    # Checked ahead of "is anything even enrolled": the recovery key requires
    # .env-file access on the machine itself, a higher trust bar than a browser
    # session, and it's meant to work precisely when no working fingerprint is
    # reachable — including the case where none was ever enrolled.
    if recovery_ok(recovery_key):
        audit(op, True, reason="recovery key used", detail=detail)
        raise_threat("recovery_key_used",
                     f"recovery key used to authorise {op}", severity="warn")
        return

    if not enrolled():
        # Failing open here would make REQUIRE_BIOMETRIC a lie; failing closed
        # with a clear instruction is the honest behaviour.
        audit(op, False, reason="no fingerprint enrolled", detail=detail)
        raise Denied("No fingerprint is enrolled yet. Open the dashboard and add "
                     "this device under Security, then try again.")

    if presence_ok(presence_token):
        audit(op, True, reason="biometric presence", detail=detail)
        return

    audit(op, False, reason="no valid biometric presence", detail=detail)
    raise Denied(f"That needs your fingerprint — {PROTECTED_OPS[op]}.")


# ── threat monitor ────────────────────────────────────────────────

WATCHED_FILES = ("server/guardian.py", "server/orchestrator.py", "server/evolution.py",
                 "server/config.py", "server/main.py")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_baseline() -> dict:
    """Record hashes of the files that define Mehltani's own behaviour.

    Tampering with these is how you would quietly neuter the guardian, so a
    change to any of them that did not come through the evolution pipeline is
    worth surfacing loudly.
    """
    conn = connect()
    root = config.ROOT
    recorded = 0
    for rel in WATCHED_FILES:
        path = root / rel
        if not path.exists():
            continue
        conn.execute("INSERT INTO baseline (path, sha256, seen_at) VALUES (?,?,?) "
                     "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,"
                     " seen_at=excluded.seen_at",
                     (rel, _hash_file(path), _now()))
        recorded += 1
    conn.commit()
    return {"baselined": recorded}


def check_integrity() -> list[dict]:
    findings = []
    conn = connect()
    for row in conn.execute("SELECT * FROM baseline"):
        path = config.ROOT / row["path"]
        if not path.exists():
            findings.append({"path": row["path"], "issue": "file is missing"})
            continue
        if _hash_file(path) != row["sha256"]:
            findings.append({"path": row["path"], "issue": "contents changed since baseline"})
    return findings


def check_exposure() -> list[dict]:
    """Is this server reachable by more than it should be?"""
    findings = []
    if config.HOST in ("0.0.0.0", "::") and not config.ACCESS_TOKEN:
        findings.append({
            "issue": "listening on every network interface with no ACCESS_TOKEN",
            "fix": "set ACCESS_TOKEN in Settings, or bind HOST to 127.0.0.1"})
    if config.ALLOW_SHELL and not config.REQUIRE_BIOMETRIC:
        findings.append({
            "issue": "shell execution is on and the biometric gate is off",
            "fix": "turn REQUIRE_BIOMETRIC on, or turn ALLOW_SHELL off"})
    if config.ACCESS_TOKEN and len(config.ACCESS_TOKEN) < 16:
        findings.append({"issue": "ACCESS_TOKEN is short enough to guess",
                         "fix": "use at least 24 random characters"})
    if config.REQUIRE_BIOMETRIC and not enrolled():
        findings.append({"issue": "biometric gate is on but no device is enrolled",
                         "fix": "enrol a fingerprint under Security"})
    return findings


def check_listeners() -> list[dict]:
    """Unexpected listening sockets — the cheapest useful intrusion signal."""
    try:
        import psutil
    except ImportError:
        return []
    expected = {config.PORT, 22, 53, 631, 5353}
    findings = []
    seen: set[int] = set()
    try:
        for conn_info in psutil.net_connections(kind="inet"):
            if conn_info.status != "LISTEN" or not conn_info.laddr:
                continue
            port = conn_info.laddr.port
            addr = conn_info.laddr.ip
            if port in expected or port in seen:
                continue
            # Loopback-only listeners are normal developer noise; a listener on a
            # routable address is the one worth a second look.
            if addr in ("127.0.0.1", "::1"):
                continue
            seen.add(port)
            name = ""
            try:
                if conn_info.pid:
                    name = psutil.Process(conn_info.pid).name()
            except Exception:
                pass
            findings.append({"port": port, "address": addr, "process": name})
    except (psutil.AccessDenied, PermissionError):
        return [{"note": "listening-socket scan needs elevated permissions on this OS"}]
    return findings[:12]


def scan() -> dict:
    """Run every check and record anything that looks wrong."""
    integrity = check_integrity()
    exposure = check_exposure()
    listeners = check_listeners()

    for finding in integrity:
        raise_threat("integrity", f"{finding['path']}: {finding['issue']}",
                     severity="critical", detail=finding)
    for finding in exposure:
        raise_threat("exposure", finding["issue"], severity="warn", detail=finding)

    posture = "critical" if integrity else ("warn" if exposure else "ok")
    return {
        "posture": posture,
        "checked_at": _now(),
        "integrity": integrity or "all watched files match baseline",
        "exposure": exposure or "no exposure problems found",
        "unexpected_listeners": listeners,
        "biometrics": {"available": biometrics_available()[1],
                       "enrolled": len(credentials()),
                       "gate_on": config.REQUIRE_BIOMETRIC},
        "lockdown": lockdown_state(),
        "recent_denials": len(audit_log(limit=25, only_denied=True)),
    }


def status() -> dict:
    """Cheap summary for the dashboard tile — no filesystem hashing."""
    ok, detail = biometrics_available()
    return {
        "biometrics_available": ok,
        "biometrics_detail": detail,
        "enrolled_devices": len(credentials()),
        "gate_on": config.REQUIRE_BIOMETRIC,
        "lockdown": lockdown_state(),
        "open_threats": len(threat_log(unresolved_only=True)),
        "protected_operations": sorted(PROTECTED_OPS),
    }
