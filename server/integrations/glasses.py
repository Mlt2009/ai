"""Meta glasses — getting what you see into Mehltani.

READ THIS BEFORE EXPECTING MORE THAN IT DOES
---------------------------------------------
Ray-Ban Meta glasses have no open third-party SDK that lets an app on your own
machine stream the camera. Meta's Wearables Device Access Toolkit exists but is
a gated developer preview: you apply, you get approved, and it targets apps
published through Meta's own surfaces. Anything claiming a drop-in "connect to
Meta glasses" library today is either using one of the two routes below or is
not telling you the truth.

So this module implements the two routes that genuinely work right now, and
leaves a clearly-marked seam for the toolkit if your access comes through.

ROUTE 1 — voice send to WhatsApp (works today, zero setup beyond WhatsApp)
    "Hey Meta, send a photo to Mehltani."
    The glasses capture, hand off to your phone, and the image arrives on the
    WhatsApp Business number. The webhook in main.py picks it up, Mehltani looks
    at it, and answers in the thread — which the glasses will read back to you.
    This is the closest thing to a live "what am I looking at" loop, and it is
    the reason WhatsApp is the centre of this design rather than an add-on.

ROUTE 2 — watch folder (works today, best quality)
    Glasses sync to the Meta AI app, which saves to your phone's camera roll,
    which syncs to a folder on this machine via iCloud Photos, Google Photos
    desktop, Dropbox, OneDrive or Syncthing. Point GLASSES_WATCH_DIR at it and
    every new capture is ingested automatically at full resolution.
    Higher latency than route 1, much better for anything you intend to shoot.

ROUTE 3 — Wearables Device Access Toolkit (when your access lands)
    `toolkit_status()` is the seam. Fill in the client and the rest of the
    pipeline downstream of ingest() does not change at all.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config

log = logging.getLogger("glasses")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov"}
STATE_FILE = "glasses_seen.json"


def uploads_dir() -> Path:
    """Shared with the scan agent so every image has one home."""
    path = Path(config.DATA_DIR) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return Path(config.DATA_DIR) / STATE_FILE


def _seen() -> dict[str, float]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _remember(seen: dict[str, float]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the ledger from growing without bound on a busy camera roll.
    if len(seen) > 5000:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:2500])
    path.write_text(json.dumps(seen))


def watch_configured() -> bool:
    return bool(config.GLASSES_WATCH_DIR and Path(config.GLASSES_WATCH_DIR).is_dir())


def ingest(limit: int = 12, min_age_seconds: int = 5) -> list[dict]:
    """Copy new captures out of the watch folder into the uploads directory.

    `min_age_seconds` avoids grabbing a file mid-sync: a cloud client writes a
    partial file first, and reading it produces a corrupt image that the vision
    model then confidently describes as something it is not.
    """
    if not watch_configured():
        return []
    source = Path(config.GLASSES_WATCH_DIR)
    seen = _seen()
    now = time.time()
    fresh: list[dict] = []

    candidates = [p for p in source.rglob("*")
                  if p.is_file() and p.suffix.lower() in (IMAGE_SUFFIXES | VIDEO_SUFFIXES)]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for path in candidates:
        key = f"{path.name}:{path.stat().st_size}"
        if key in seen:
            continue
        if now - path.stat().st_mtime < min_age_seconds:
            continue
        image_id = f"glasses_{int(path.stat().st_mtime)}_{path.stem[:14]}{path.suffix.lower()}"
        target = uploads_dir() / image_id
        try:
            shutil.copy2(path, target)
        except OSError as exc:
            log.warning("could not ingest %s: %s", path.name, exc)
            continue
        seen[key] = now
        fresh.append({
            "image_id": image_id,
            "source_name": path.name,
            "kind": "video" if path.suffix.lower() in VIDEO_SUFFIXES else "image",
            "captured_at": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "kb": round(target.stat().st_size / 1024),
        })
        if len(fresh) >= limit:
            break

    if fresh:
        _remember(seen)
        log.info("ingested %d capture(s) from the glasses watch folder", len(fresh))
    return fresh


def mark_all_seen() -> int:
    """Baseline an existing folder so the first run does not ingest ten years
    of camera roll."""
    if not watch_configured():
        return 0
    source = Path(config.GLASSES_WATCH_DIR)
    seen = _seen()
    count = 0
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() in (IMAGE_SUFFIXES | VIDEO_SUFFIXES):
            seen[f"{path.name}:{path.stat().st_size}"] = time.time()
            count += 1
    _remember(seen)
    return count


def latest(count: int = 1) -> list[str]:
    """Newest ingested capture ids — 'what am I looking at' resolves to these."""
    files = sorted(uploads_dir().glob("*.*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in files[:count]]


def toolkit_status() -> dict:
    """Route 3 seam — Meta's Wearables Device Access Toolkit.

    Deliberately reports the truth rather than pretending to be connected. When
    your developer access is approved, implement the streaming client here and
    have it write frames into uploads_dir(); everything downstream — the style
    agent, the photoshoot agent, the WhatsApp loop — already reads from there
    and will not need a single change.
    """
    return {
        "available": False,
        "reason": "Meta's Wearables Device Access Toolkit is an approval-gated "
                  "developer preview; there is no public streaming API for "
                  "Ray-Ban Meta glasses on a self-hosted app yet.",
        "working_alternatives": [
            "Say 'Hey Meta, send a photo to <your WhatsApp Business number>' — it "
            "arrives on the webhook within seconds and Mehltani replies in the thread.",
            "Sync your camera roll to a folder and set GLASSES_WATCH_DIR — full "
            "resolution, ingested automatically.",
        ],
    }


def status() -> dict:
    configured = watch_configured()
    return {
        "watch_folder": config.GLASSES_WATCH_DIR or "(not set)",
        "watch_active": configured,
        "captures_ingested": len(_seen()),
        "whatsapp_route": "the reliable path — see integrations/whatsapp.py",
        "toolkit": toolkit_status(),
        "detail": (f"watching {config.GLASSES_WATCH_DIR}" if configured
                   else "set GLASSES_WATCH_DIR to a synced camera-roll folder, "
                        "or just send photos over WhatsApp"),
    }
