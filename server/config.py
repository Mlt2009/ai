"""Central configuration loaded from environment / .env file.

Supports hot-reload: the Settings panel in the web app writes new values
to .env and calls reload(), so agents pick up keys without a restart
(they read config attributes at call time).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# Keys the Settings panel is allowed to manage.
EDITABLE_KEYS = [
    "GEMINI_API_KEY", "GEMINI_MODEL", "BRAIN_PROVIDER",
    "HA_URL", "HA_TOKEN",
    "OCTOPRINT_URL", "OCTOPRINT_API_KEY",
    "CUPS_PRINTER",
    "WEATHER_LAT", "WEATHER_LON",
    "ELEVENLABS_API_KEY",
    "ALLOW_SHELL",
    # AI companions the Council agent broadcasts to
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
    "COMPANION_ENDPOINTS",
    # Receipt / print layout
    "BUSINESS_NAME", "BUSINESS_PHONE", "RECEIPT_WIDTH", "RECEIPT_FOOTER",
    # Invoicing + mileage
    "TAX_RATE", "INVOICE_TERMS_DAYS", "MILEAGE_RATE",
    # Email
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
    "IMAP_HOST", "IMAP_PORT",
    # File control
    "FILE_ROOTS", "ALLOW_FILE_WRITE",
    # Remote access
    "ACCESS_TOKEN",
]

# Secrets that must never be echoed back to a client in full.
SECRET_KEYS = {"GEMINI_API_KEY", "HA_TOKEN", "OCTOPRINT_API_KEY", "ELEVENLABS_API_KEY",
               "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
               "ACCESS_TOKEN", "SMTP_PASSWORD"}


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _flag(key: str, default: str = "false") -> bool:
    return env(key, default).lower() in ("1", "true", "yes", "on")


def reload() -> None:
    """(Re)read .env and refresh module-level settings."""
    global GEMINI_API_KEY, GEMINI_MODEL, HA_URL, HA_TOKEN
    global OCTOPRINT_URL, OCTOPRINT_API_KEY, CUPS_PRINTER
    global HOST, PORT, WEATHER_LAT, WEATHER_LON, ALLOW_SHELL, DATA_DIR
    global BRAIN_PROVIDER
    global ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OPENAI_API_KEY, OPENAI_MODEL
    global OPENROUTER_API_KEY, OPENROUTER_MODEL, COMPANION_ENDPOINTS
    global OPENAI_BASE_URL
    global BUSINESS_NAME, BUSINESS_PHONE, RECEIPT_WIDTH, RECEIPT_FOOTER
    global FILE_ROOTS, ALLOW_FILE_WRITE, ACCESS_TOKEN
    global TAX_RATE, INVOICE_TERMS_DAYS, MILEAGE_RATE
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    global IMAP_HOST, IMAP_PORT

    load_dotenv(ENV_PATH, override=True)

    GEMINI_API_KEY = env("GEMINI_API_KEY")
    # "latest" alias tracks Google's newest fast model, so it never retires.
    GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")

    # Which model drives Atlas: "auto" (Gemini if keyed, else OpenAI),
    # or pin one with "gemini" / "openai".
    BRAIN_PROVIDER = env("BRAIN_PROVIDER", "auto").lower()

    HA_URL = env("HA_URL", "http://homeassistant.local:8123").rstrip("/")
    HA_TOKEN = env("HA_TOKEN")

    OCTOPRINT_URL = env("OCTOPRINT_URL", "http://octopi.local").rstrip("/")
    OCTOPRINT_API_KEY = env("OCTOPRINT_API_KEY")

    CUPS_PRINTER = env("CUPS_PRINTER")

    HOST = env("HOST", "0.0.0.0")
    PORT = int(env("PORT", "8000"))

    WEATHER_LAT = float(env("WEATHER_LAT", "40.71") or "40.71")
    WEATHER_LON = float(env("WEATHER_LON", "-74.01") or "-74.01")

    ALLOW_SHELL = _flag("ALLOW_SHELL")

    DATA_DIR = env("DATA_DIR") or str(ROOT / "data")

    # ── AI companions (Council agent) ─────────────────────────────
    ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-opus-5")
    OPENAI_API_KEY = env("OPENAI_API_KEY")
    OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o")
    # Point at a proxy, Azure gateway or local server if you don't use api.openai.com
    OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = env("OPENROUTER_MODEL", "openrouter/auto")
    # name|base_url|model|api_key, comma separated — any OpenAI-compatible server
    COMPANION_ENDPOINTS = env("COMPANION_ENDPOINTS")

    # ── printed slip layout ───────────────────────────────────────
    BUSINESS_NAME = env("BUSINESS_NAME")
    BUSINESS_PHONE = env("BUSINESS_PHONE")
    RECEIPT_WIDTH = int(env("RECEIPT_WIDTH", "32") or "32")
    RECEIPT_FOOTER = env("RECEIPT_FOOTER", "Thank you for your business")

    # ── invoicing + mileage ───────────────────────────────────────
    TAX_RATE = float(env("TAX_RATE", "0") or "0")
    INVOICE_TERMS_DAYS = int(env("INVOICE_TERMS_DAYS", "30") or "30")
    # Per-mile deduction rate. NOT hardcoded to a published figure: rates change
    # every tax year, and a stale one would put a wrong number on a return.
    # Set this to the rate published for your tax year and jurisdiction.
    MILEAGE_RATE = float(env("MILEAGE_RATE", "0") or "0")

    # ── email ─────────────────────────────────────────────────────
    SMTP_HOST = env("SMTP_HOST")
    SMTP_PORT = int(env("SMTP_PORT", "587") or "587")
    SMTP_USER = env("SMTP_USER")
    SMTP_PASSWORD = env("SMTP_PASSWORD")   # Gmail: an app password, not your login
    SMTP_FROM = env("SMTP_FROM")
    IMAP_HOST = env("IMAP_HOST")
    IMAP_PORT = int(env("IMAP_PORT", "993") or "993")

    # ── file control ──────────────────────────────────────────────
    # os.pathsep-separated folders the Files agent may touch; "*" = everywhere.
    FILE_ROOTS = env("FILE_ROOTS", str(Path.home()))
    ALLOW_FILE_WRITE = _flag("ALLOW_FILE_WRITE")

    # ── remote access ─────────────────────────────────────────────
    # When set, every API/WebSocket call must present this token. Set it before
    # exposing the server beyond your own network.
    ACCESS_TOKEN = env("ACCESS_TOKEN")


def save(updates: dict[str, str]) -> list[str]:
    """Write the given key=value pairs into .env (create it if missing),
    preserving other lines, then hot-reload. Returns the keys changed."""
    updates = {k: str(v).strip() for k, v in updates.items()
               if k in EDITABLE_KEYS and v is not None}
    if not updates:
        return []
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    reload()
    return sorted(updates)


reload()
