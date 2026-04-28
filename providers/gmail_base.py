from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import config
from oauth2 import refresher

log = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def is_gmail_configured() -> bool:
    return bool(config.GMAIL_CLIENT_ID and config.GMAIL_CLIENT_SECRET)


def _token() -> str:
    return refresher.get_valid_token(
        provider="gmail",
        token_url=_TOKEN_URL,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
    )


def search_messages(query: str, since: date) -> list[dict]:
    """Return Gmail message stubs (id + threadId) matching query since date."""
    headers = {"Authorization": f"Bearer {_token()}"}
    full_query = f"{query} after:{since.strftime('%Y/%m/%d')}"
    resp = requests.get(
        f"{_GMAIL_API}/messages",
        headers=headers,
        params={"q": full_query, "maxResults": 50},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("messages", [])


def get_message(msg_id: str) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    resp = requests.get(
        f"{_GMAIL_API}/messages/{msg_id}",
        headers=headers,
        params={"format": "full"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_attachment_bytes(msg_id: str, attachment_id: str) -> bytes:
    headers = {"Authorization": f"Bearer {_token()}"}
    resp = requests.get(
        f"{_GMAIL_API}/messages/{msg_id}/attachments/{attachment_id}",
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json().get("data", "")
    return base64.urlsafe_b64decode(data + "==")


def find_pdf_parts(msg: dict) -> list[dict]:
    """Return list of PDF attachment descriptors found in a message."""
    result: list[dict] = []
    _walk_parts(msg.get("payload", {}), result)
    return result


def _walk_parts(payload: dict, result: list) -> None:
    mime = payload.get("mimeType", "")
    filename = payload.get("filename", "")
    body = payload.get("body", {})
    attachment_id = body.get("attachmentId")
    if attachment_id and (
        mime == "application/pdf" or filename.lower().endswith(".pdf")
    ):
        result.append({
            "attachment_id": attachment_id,
            "filename": filename or "invoice.pdf",
            "size": body.get("size", 0),
        })
    for part in payload.get("parts", []):
        _walk_parts(part, result)


def get_header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def msg_date(msg: dict) -> date:
    ms = int(msg.get("internalDate", 0))
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
