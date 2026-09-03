"""Outside-world connectors: the phone, the two workspaces, the glasses.

Each module here is a thin, honest client over a real API. They deliberately do
not depend on each other, so a missing WhatsApp token cannot stop Gmail from
working, and every one of them degrades to a clear "not configured yet" message
rather than an exception.
"""
from . import glasses, google_ws, microsoft_ws, whatsapp

__all__ = ["whatsapp", "google_ws", "microsoft_ws", "glasses"]
