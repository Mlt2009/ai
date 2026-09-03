"""Microsoft 365 — Outlook mail, OneDrive, Calendar and Teams via Graph.

Same shape as google_ws.py deliberately: refresh token in, access token cached,
plain REST out. If you only use one of the two workspaces the other simply
reports "not connected" and nothing else changes.

Getting a refresh token, once:
  1. entra.microsoft.com > App registrations > New registration
     - supported accounts: personal + work/school, whichever you use
     - redirect URI: Public client/native > http://localhost
  2. Certificates & secrets > New client secret (note the *value*)
  3. API permissions > Microsoft Graph > Delegated: Mail.ReadWrite, Mail.Send,
     Files.ReadWrite, Calendars.ReadWrite, Chat.ReadWrite, offline_access
  4. run `python -m server.integrations.microsoft_ws`

Tenant note: `common` works for both personal Microsoft accounts and work
accounts. Pin MS_TENANT to your tenant GUID if your admin requires it.
"""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from .. import config

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 45.0

SCOPES = ["offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send",
          "Files.ReadWrite", "Calendars.ReadWrite", "Chat.ReadWrite"]

_token: dict[str, Any] = {"value": "", "expires": 0.0}


def configured() -> bool:
    return bool(config.MS_CLIENT_ID and config.MS_REFRESH_TOKEN)


def _token_url() -> str:
    return (f"https://login.microsoftonline.com/{config.MS_TENANT or 'common'}"
            "/oauth2/v2.0/token")


async def access_token() -> str:
    if _token["value"] and _token["expires"] > time.time() + 60:
        return _token["value"]
    if not configured():
        raise RuntimeError(
            "Microsoft 365 is not connected — add MS_CLIENT_ID, MS_CLIENT_SECRET "
            "and MS_REFRESH_TOKEN in Settings (run "
            "`python -m server.integrations.microsoft_ws` to get the refresh token)")
    data = {"client_id": config.MS_CLIENT_ID, "grant_type": "refresh_token",
            "refresh_token": config.MS_REFRESH_TOKEN, "scope": " ".join(SCOPES)}
    if config.MS_CLIENT_SECRET:
        data["client_secret"] = config.MS_CLIENT_SECRET
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(_token_url(), data=data)
    if response.status_code >= 400:
        raise RuntimeError(f"Microsoft token refresh failed ({response.status_code}): "
                           f"{response.text[:220]}")
    body = response.json()
    _token["value"] = body["access_token"]
    _token["expires"] = time.time() + float(body.get("expires_in", 3600))
    # Microsoft rotates refresh tokens; persist the new one or the connection
    # silently dies the next time the old one expires.
    if body.get("refresh_token") and body["refresh_token"] != config.MS_REFRESH_TOKEN:
        config.save({"MS_REFRESH_TOKEN": body["refresh_token"]})
    return _token["value"]


async def _call(method: str, path: str, **kwargs) -> Any:
    token = await access_token()
    headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(method, f"{GRAPH}{path}", headers=headers, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Graph {method} {path} -> HTTP {response.status_code}: "
                           f"{response.text[:300]}")
    return response.json() if response.content else {}


# ── Outlook mail ──────────────────────────────────────────────────

async def list_mail(query: str = "", limit: int = 10, folder: str = "inbox") -> list[dict]:
    params: dict[str, Any] = {"$top": min(int(limit), 40),
                              "$select": "id,subject,from,toRecipients,receivedDateTime,"
                                         "bodyPreview,isRead,conversationId",
                              "$orderby": "receivedDateTime desc"}
    path = f"/me/mailFolders/{folder}/messages"
    if query:
        params["$search"] = f'"{query}"'
        params.pop("$orderby")  # Graph rejects $search combined with $orderby
        path = "/me/messages"
    body = await _call("GET", path, params=params)
    return [{"id": m.get("id"),
             "thread_id": m.get("conversationId"),
             "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address", ""),
             "to": [((r.get("emailAddress") or {}).get("address", ""))
                    for r in m.get("toRecipients") or []],
             "subject": m.get("subject", ""),
             "date": m.get("receivedDateTime", ""),
             "snippet": m.get("bodyPreview", ""),
             "unread": not m.get("isRead", True)}
            for m in body.get("value", [])]


async def send_mail(to: str, subject: str, body: str, cc: str = "") -> dict:
    """Send Outlook mail. Gate behind guardian 'send_external'."""
    def recipients(raw: str) -> list[dict]:
        return [{"emailAddress": {"address": a.strip()}}
                for a in raw.split(",") if a.strip()]

    payload = {"message": {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": recipients(to),
        "ccRecipients": recipients(cc)}, "saveToSentItems": True}
    await _call("POST", "/me/sendMail", json=payload)
    return {"sent": True, "to": to, "subject": subject}


async def mark_read(message_id: str, read: bool = True) -> dict:
    await _call("PATCH", f"/me/messages/{message_id}", json={"isRead": read})
    return {"id": message_id, "read": read}


# ── OneDrive ──────────────────────────────────────────────────────

async def search_drive(query: str, limit: int = 20) -> list[dict]:
    body = await _call("GET", f"/me/drive/root/search(q='{query}')",
                       params={"$top": min(int(limit), 50)})
    return [{"id": f.get("id"), "name": f.get("name"),
             "size": f.get("size"), "modified": f.get("lastModifiedDateTime"),
             "url": f.get("webUrl")} for f in body.get("value", [])]


async def download_file(item_id: str) -> bytes:
    token = await access_token()
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        response = await client.get(f"{GRAPH}/me/drive/items/{item_id}/content",
                                    headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.content


async def upload_file(name: str, content: bytes, folder: str = "Mehltani") -> dict:
    """Simple upload — Graph's small-file path tops out around 4 MB."""
    token = await access_token()
    path = f"/me/drive/root:/{folder}/{name}:/content"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.put(f"{GRAPH}{path}", content=content,
                                    headers={"Authorization": f"Bearer {token}",
                                             "Content-Type": "application/octet-stream"})
    if response.status_code >= 400:
        raise RuntimeError(f"OneDrive upload failed ({response.status_code}): "
                           f"{response.text[:200]}")
    body = response.json()
    return {"id": body.get("id"), "name": body.get("name"), "url": body.get("webUrl")}


# ── Calendar and Teams ────────────────────────────────────────────

async def list_events(days: int = 7) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    body = await _call("GET", "/me/calendarView", params={
        "startDateTime": now.isoformat(),
        "endDateTime": (now + timedelta(days=int(days))).isoformat(),
        "$orderby": "start/dateTime", "$top": 50})
    return [{"id": e.get("id"), "summary": e.get("subject", "(no title)"),
             "start": (e.get("start") or {}).get("dateTime"),
             "end": (e.get("end") or {}).get("dateTime"),
             "location": ((e.get("location") or {}).get("displayName", "")),
             "online": (e.get("onlineMeeting") or {}).get("joinUrl", "")}
            for e in body.get("value", [])]


async def create_event(summary: str, start_iso: str, end_iso: str, *,
                       location: str = "", description: str = "",
                       attendees: list[str] | None = None) -> dict:
    payload: dict[str, Any] = {
        "subject": summary,
        "body": {"contentType": "Text", "content": description},
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
        "location": {"displayName": location}}
    if attendees:
        payload["attendees"] = [{"emailAddress": {"address": a}, "type": "required"}
                                for a in attendees]
    created = await _call("POST", "/me/events", json=payload)
    return {"id": created.get("id"), "summary": summary, "start": start_iso,
            "link": created.get("webLink", "")}


async def send_teams_message(chat_id: str, text: str) -> dict:
    await _call("POST", f"/chats/{chat_id}/messages",
                json={"body": {"content": text}})
    return {"sent": True, "chat_id": chat_id}


async def list_teams_chats(limit: int = 15) -> list[dict]:
    body = await _call("GET", "/me/chats", params={"$top": min(int(limit), 50)})
    return [{"id": c.get("id"), "topic": c.get("topic") or "(direct)",
             "type": c.get("chatType"), "updated": c.get("lastUpdatedDateTime")}
            for c in body.get("value", [])]


async def check() -> dict:
    if not configured():
        return {"on": False, "detail": "no Microsoft OAuth credentials"}
    try:
        me = await _call("GET", "/me")
        return {"on": True, "detail": f"connected · {me.get('userPrincipalName', '')}"}
    except Exception as exc:
        return {"on": False, "detail": f"{type(exc).__name__}: {str(exc)[:140]}"}


# ── one-time setup helper ─────────────────────────────────────────

def _setup_cli() -> None:
    import urllib.parse
    import webbrowser

    client_id = input("Microsoft application (client) ID: ").strip()
    client_secret = input("Client secret value (blank for public client): ").strip()
    tenant = input("Tenant [common]: ").strip() or "common"
    redirect = "http://localhost"
    url = (f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
           + urllib.parse.urlencode({
               "client_id": client_id, "response_type": "code",
               "redirect_uri": redirect, "response_mode": "query",
               "scope": " ".join(SCOPES)}))
    print("\n1. Open this URL and approve access:\n")
    print(url)
    print("\n2. You will land on a localhost page that fails to load — that is")
    print("   expected. Copy the `code=` value from the address bar.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = input("code: ").strip()
    data = {"client_id": client_id, "grant_type": "authorization_code",
            "code": code, "redirect_uri": redirect, "scope": " ".join(SCOPES)}
    if client_secret:
        data["client_secret"] = client_secret
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=data)
    if response.status_code >= 400:
        print(f"\nFailed: {response.status_code} {response.text}")
        return
    print("\nAdd these to your .env:\n")
    print(f"MS_CLIENT_ID={client_id}")
    if client_secret:
        print(f"MS_CLIENT_SECRET={client_secret}")
    print(f"MS_TENANT={tenant}")
    print(f"MS_REFRESH_TOKEN={response.json().get('refresh_token', '')}")


if __name__ == "__main__":
    _setup_cli()
