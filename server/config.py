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
    # File control
    "FILE_ROOTS", "ALLOW_FILE_WRITE",
    # Remote access
    "ACCESS_TOKEN",
    # Mehltani: identity and the biometric gate
    "OWNER_NAME", "RP_ID", "EXTRA_ORIGINS", "REQUIRE_BIOMETRIC", "RECOVERY_KEY",
    "AUTO_LOCKDOWN",
    # Mehltani: the phone
    "WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET", "WHATSAPP_OWNER",
    # Mehltani: Google Workspace
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN",
    # Mehltani: Microsoft 365
    "MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT", "MS_REFRESH_TOKEN",
    # Mehltani: glasses and image generation
    "GLASSES_WATCH_DIR", "GEMINI_IMAGE_MODEL", "OPENAI_IMAGE_MODEL",
]

# Secrets that must never be echoed back to a client in full.
SECRET_KEYS = {"GEMINI_API_KEY", "HA_TOKEN", "OCTOPRINT_API_KEY", "ELEVENLABS_API_KEY",
               "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ACCESS_TOKEN",
               "RECOVERY_KEY", "WHATSAPP_TOKEN", "WHATSAPP_VERIFY_TOKEN",
               "WHATSAPP_APP_SECRET", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN",
               "MS_CLIENT_SECRET", "MS_REFRESH_TOKEN"}


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
    global OWNER_NAME, RP_ID, EXTRA_ORIGINS, REQUIRE_BIOMETRIC, RECOVERY_KEY, AUTO_LOCKDOWN
    global WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_VERIFY_TOKEN
    global WHATSAPP_APP_SECRET, WHATSAPP_OWNER
    global GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
    global MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT, MS_REFRESH_TOKEN
    global GLASSES_WATCH_DIR, GEMINI_IMAGE_MODEL, OPENAI_IMAGE_MODEL

    load_dotenv(ENV_PATH, override=True)

    GEMINI_API_KEY = env("GEMINI_API_KEY")
    # "latest" alias tracks Google's newest fast model, so it never retires.
    GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")

    # Which model drives Mehltani: "auto" (Gemini if keyed, else OpenAI),
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

    # ── file control ──────────────────────────────────────────────
    # os.pathsep-separated folders the Files agent may touch; "*" = everywhere.
    FILE_ROOTS = env("FILE_ROOTS", str(Path.home()))
    ALLOW_FILE_WRITE = _flag("ALLOW_FILE_WRITE")

    # ── remote access ─────────────────────────────────────────────
    # When set, every API/WebSocket call must present this token. Set it before
    # exposing the server beyond your own network.
    ACCESS_TOKEN = env("ACCESS_TOKEN")

    # ── identity and the biometric gate ────────────────────────────
    OWNER_NAME = env("OWNER_NAME", "Owner")
    # The domain the dashboard is served from — WebAuthn binds credentials to
    # this, so it must match what's in the browser's address bar (no scheme,
    # no port). "localhost" works for local-only use.
    RP_ID = env("RP_ID", "localhost")
    # Comma-separated extra origins (e.g. a tunnel URL) allowed to complete a
    # WebAuthn ceremony, beyond the two derived from RP_ID.
    EXTRA_ORIGINS = env("EXTRA_ORIGINS")
    REQUIRE_BIOMETRIC = _flag("REQUIRE_BIOMETRIC", "true")
    RECOVERY_KEY = env("RECOVERY_KEY")
    AUTO_LOCKDOWN = _flag("AUTO_LOCKDOWN", "true")

    # ── WhatsApp Business Cloud API ─────────────────────────────────
    WHATSAPP_TOKEN = env("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_ID = env("WHATSAPP_PHONE_ID")
    WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET")
    WHATSAPP_OWNER = env("WHATSAPP_OWNER")

    # ── Google Workspace ─────────────────────────────────────────────
    GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
    GOOGLE_REFRESH_TOKEN = env("GOOGLE_REFRESH_TOKEN")

    # ── Microsoft 365 ─────────────────────────────────────────────────
    MS_CLIENT_ID = env("MS_CLIENT_ID")
    MS_CLIENT_SECRET = env("MS_CLIENT_SECRET")
    MS_TENANT = env("MS_TENANT", "common")
    MS_REFRESH_TOKEN = env("MS_REFRESH_TOKEN")

    # ── glasses and image generation ─────────────────────────────────
    GLASSES_WATCH_DIR = env("GLASSES_WATCH_DIR")
    GEMINI_IMAGE_MODEL = env("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    OPENAI_IMAGE_MODEL = env("OPENAI_IMAGE_MODEL", "gpt-image-1")


def expected_origins() -> list[str]:
    """Origins WebAuthn will accept a ceremony from.

    Always both schemes for the bare RP_ID (a dev server is commonly plain
    http on the LAN, a tunnel is https), plus whatever the owner added
    explicitly for a tunnel/reverse-proxy host.
    """
    origins = {f"https://{RP_ID}", f"http://{RP_ID}"}
    if RP_ID == "localhost":
        origins.add(f"http://{RP_ID}:{PORT}")
    for extra in (EXTRA_ORIGINS or "").split(","):
        extra = extra.strip()
        if extra:
            origins.add(extra if "://" in extra else f"https://{extra}")
    return sorted(origins)


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
