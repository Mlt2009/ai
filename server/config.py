"""Central configuration loaded from environment / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-2.0-flash")

HA_URL = env("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN = env("HA_TOKEN")

OCTOPRINT_URL = env("OCTOPRINT_URL", "http://octopi.local").rstrip("/")
OCTOPRINT_API_KEY = env("OCTOPRINT_API_KEY")

CUPS_PRINTER = env("CUPS_PRINTER")

HOST = env("HOST", "0.0.0.0")
PORT = int(env("PORT", "8000"))

WEATHER_LAT = float(env("WEATHER_LAT", "40.71"))
WEATHER_LON = float(env("WEATHER_LON", "-74.01"))

ALLOW_SHELL = env("ALLOW_SHELL", "false").lower() == "true"
