"""Central configuration loaded from environment / .env file.

Supports hot-reload: the Settings panel in the web app writes new values
to .env and calls reload(), so agents pick up keys without a restart
(they read config attributes at call time).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Keys the Settings panel is allowed to manage.
EDITABLE_KEYS = [
    "GEMINI_API_KEY", "GEMINI_MODEL",
    "HA_URL", "HA_TOKEN",
    "OCTOPRINT_URL", "OCTOPRINT_API_KEY",
    "CUPS_PRINTER",
    "WEATHER_LAT", "WEATHER_LON",
    "ELEVENLABS_API_KEY",
    "ALLOW_SHELL",
]


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def reload() -> None:
    """(Re)read .env and refresh module-level settings."""
    global GEMINI_API_KEY, GEMINI_MODEL, HA_URL, HA_TOKEN
    global OCTOPRINT_URL, OCTOPRINT_API_KEY, CUPS_PRINTER
    global HOST, PORT, WEATHER_LAT, WEATHER_LON, ALLOW_SHELL

    load_dotenv(ENV_PATH, override=True)

    GEMINI_API_KEY = env("GEMINI_API_KEY")
    # "latest" alias tracks Google's newest fast model, so it never retires.
    GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-latest")

    HA_URL = env("HA_URL", "http://homeassistant.local:8123").rstrip("/")
    HA_TOKEN = env("HA_TOKEN")

    OCTOPRINT_URL = env("OCTOPRINT_URL", "http://octopi.local").rstrip("/")
    OCTOPRINT_API_KEY = env("OCTOPRINT_API_KEY")

    CUPS_PRINTER = env("CUPS_PRINTER")

    HOST = env("HOST", "0.0.0.0")
    PORT = int(env("PORT", "8000"))

    WEATHER_LAT = float(env("WEATHER_LAT", "40.71") or "40.71")
    WEATHER_LON = float(env("WEATHER_LON", "-74.01") or "-74.01")

    ALLOW_SHELL = env("ALLOW_SHELL", "false").lower() == "true"


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
