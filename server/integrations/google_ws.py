"""Google Workspace — Gmail, Drive and Calendar over plain REST.

No Google SDK on purpose. The official client libraries drag in a large
dependency tree and their own credential storage, and all we need is a refresh
token exchanged for an access token plus a handful of documented endpoints.
Fewer moving parts means fewer ways for the assistant to break at 2am.

Getting a refresh token, once:
  1. console.cloud.google.com > new project > enable Gmail, Drive, Calendar APIs
  2. OAuth consent screen > External > add yourself as a test user
  3. Credentials > OAuth client ID > Desktop app > note id and secret
  4. run `python -m server.integrations.google_ws` and follow the printed steps

Scopes requested are read-heavy with send: Mehltani should be able to triage the
inbox and reply on your say-so, not quietly reorganise your Drive.
"""
from __future__ import annotations

import base64
import json
import time
from email.message import EmailMessage
from typing import Any

import httpx

from .. import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"
CALENDAR = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 45.0

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]

# Access tokens last an hour; cache so a busy turn is not five token round-trips.
_token: dict[str, Any] = {"value": "", "expires": 0.0}


def configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET
                and config.GOOGLE_REFRESH_TOKEN)


async def access_token() -> str:
    if _token["value"] and _token["expires"] > time.time() + 60:
        return _token["value"]
    if not configured():
        raise RuntimeError(
            "Google Workspace is not connected — add GOOGLE_CLIENT_ID, "
            "GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN in Settings "
            "(run `python -m server.integrations.google_ws` to get the refresh token)")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(TOKEN_URL, data={
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "refresh_token": config.GOOGLE_REFRESH_TOKEN,
            "grant_type": "refresh_token"})
    if response.status_code >= 400:
        raise RuntimeError(f"Google token refresh failed ({response.status_code}): "
                           f"{response.text[:200]} — the refresh token may have been "
                           "revoked; re-run the setup helper")
    body = response.json()
    _token["value"] = body["access_token"]
    _token["expires"] = time.time() + float(body.get("expires_in", 3600))
    return _token["value"]


async def _call(method: str, url: str, **kwargs) -> Any:
    token = await access_token()
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Google {method} {url.split('/')[-1]} -> "
                           f"HTTP {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


# ── Gmail ─────────────────────────────────────────────────────────

def _header(payload: dict, name: str) -> str:
    for header in (payload.get("headers") or []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _body_text(payload: dict) -> str:
    """Walk the MIME tree for the best plain-text part."""
    if payload.get("mimeType") == "text/plain":
        data = (payload.get("body") or {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
    for part in payload.get("parts") or []:
        text = _body_text(part)
        if text:
            return text
    return ""


async def list_mail(query: str = "in:inbox", limit: int = 10) -> list[dict]:
    """Search the inbox with Gmail's own query syntax (`from:`, `is:unread`...)."""
    listing = await _call("GET", f"{GMAIL}/messages",
                          params={"q": query, "maxResults": min(int(limit), 40)})
    out = []
    for stub in listing.get("messages") or []:
        message = await _call("GET", f"{GMAIL}/messages/{stub['id']}",
                              params={"format": "full"})
        payload = message.get("payload") or {}
        out.append({
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "from": _header(payload, "From"),
            "to": _header(payload, "To"),
            "subject": _header(payload, "Subject"),
            "date": _header(payload, "Date"),
            "snippet": message.get("snippet", ""),
            "unread": "UNREAD" in (message.get("labelIds") or []),
            "body": _body_text(payload)[:4000],
        })
    return out


async def send_mail(to: str, subject: str, body: str, *, cc: str = "",
                    reply_to_id: str = "") -> dict:
    """Send mail. Callers must gate this behind guardian 'send_external'."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    message.set_content(body)
    payload: dict[str, Any] = {
        "raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
    if reply_to_id:
        original = await _call("GET", f"{GMAIL}/messages/{reply_to_id}",
                               params={"format": "metadata"})
        payload["threadId"] = original.get("threadId", "")
    sent = await _call("POST", f"{GMAIL}/messages/send", json=payload)
    return {"sent": True, "id": sent.get("id"), "to": to, "subject": subject}


async def modify_labels(message_id: str, add: list[str] | None = None,
                        remove: list[str] | None = None) -> dict:
    body = {"addLabelIds": add or [], "removeLabelIds": remove or []}
    await _call("POST", f"{GMAIL}/messages/{message_id}/modify", json=body)
    return {"id": message_id, "added": add or [], "removed": remove or []}


# ── Drive ─────────────────────────────────────────────────────────

async def search_drive(query: str = "", limit: int = 20) -> list[dict]:
    q = f"name contains '{query}' and trashed = false" if query else "trashed = false"
    body = await _call("GET", f"{DRIVE}/files", params={
        "q": q, "pageSize": min(int(limit), 100),
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)"})
    return body.get("files", [])


async def download_drive_file(file_id: str) -> bytes:
    """Binary download. Native Google docs are exported as PDF automatically."""
    token = await access_token()
    meta = await _call("GET", f"{DRIVE}/files/{file_id}", params={"fields": "mimeType,name"})
    is_native = str(meta.get("mimeType", "")).startswith("application/vnd.google-apps")
    url = (f"{DRIVE}/files/{file_id}/export" if is_native
           else f"{DRIVE}/files/{file_id}")
    params = {"mimeType": "application/pdf"} if is_native else {"alt": "media"}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, params=params,
                                    headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.content


async def upload_to_drive(name: str, content: bytes, mime: str = "application/octet-stream",
                          folder_id: str = "") -> dict:
    """Multipart upload — how a finished lookbook or invoice gets filed."""
    token = await access_token()
    metadata: dict[str, Any] = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]
    boundary = "mehltani-boundary-7f3c"
    parts = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--".encode()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": f"multipart/related; boundary={boundary}"},
            content=parts)
        response.raise_for_status()
        return response.json()


# ── Calendar ──────────────────────────────────────────────────────

async def list_events(days: int = 7, calendar_id: str = "primary") -> list[dict]:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    body = await _call("GET", f"{CALENDAR}/calendars/{calendar_id}/events", params={
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=int(days))).isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": 50})
    return [{"id": e.get("id"), "summary": e.get("summary", "(no title)"),
             "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
             "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
             "location": e.get("location", ""),
             "attendees": [a.get("email") for a in e.get("attendees") or []]}
            for e in body.get("items", [])]


async def create_event(summary: str, start_iso: str, end_iso: str, *,
                       location: str = "", description: str = "",
                       attendees: list[str] | None = None,
                       calendar_id: str = "primary") -> dict:
    body: dict[str, Any] = {
        "summary": summary, "location": location, "description": description,
        "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}}
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    created = await _call("POST", f"{CALENDAR}/calendars/{calendar_id}/events", json=body)
    return {"id": created.get("id"), "summary": summary, "start": start_iso,
            "link": created.get("htmlLink", "")}


async def check() -> dict:
    if not configured():
        return {"on": False, "detail": "no Google OAuth credentials"}
    try:
        profile = await _call("GET", f"{GMAIL}/profile")
        return {"on": True, "detail": f"connected · {profile.get('emailAddress', '')} · "
                                      f"{profile.get('messagesTotal', 0)} messages"}
    except Exception as exc:
        return {"on": False, "detail": f"{type(exc).__name__}: {str(exc)[:140]}"}


# ── one-time setup helper ─────────────────────────────────────────

def _setup_cli() -> None:
    """`python -m server.integrations.google_ws` — walk through getting a token."""
    import urllib.parse
    import webbrowser

    client_id = input("Google OAuth client ID: ").strip()
    client_secret = input("Google OAuth client secret: ").strip()
    redirect = "http://localhost"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"})
    print("\n1. Open this URL and approve access:\n")
    print(url)
    print("\n2. You will land on a localhost page that fails to load. That is fine —")
    print("   copy the `code=` value out of the address bar.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = input("code: ").strip()
    with httpx.Client(timeout=30) as client:
        response = client.post(TOKEN_URL, data={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect})
    if response.status_code >= 400:
        print(f"\nFailed: {response.status_code} {response.text}")
        return
    token = response.json().get("refresh_token", "")
    print("\nAdd these three lines to your .env:\n")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={token}")


if __name__ == "__main__":
    _setup_cli()
