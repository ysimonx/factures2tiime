from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone

import requests

import config
from oauth2 import refresher

log = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Token store key for the main mailbox. Secondary mailboxes pass their own alias
# (see config.GMAIL_PERSO_ACCOUNT) — one OAuth grant per Google account.
DEFAULT_ACCOUNT = "gmail"

# Safety net for a broad query over a long look-back — see search_messages
_MAX_RESULTS = 500


def is_gmail_configured() -> bool:
    return bool(config.GMAIL_CLIENT_ID and config.GMAIL_CLIENT_SECRET)


def has_account(account: str) -> bool:
    """True when `account` has already been authorized (token stored)."""
    from oauth2 import token_store
    return is_gmail_configured() and token_store.load(account) is not None


def _token(account: str = DEFAULT_ACCOUNT) -> str:
    return refresher.get_valid_token(
        provider=account,
        token_url=_TOKEN_URL,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
    )


def search_messages(
    query: str,
    since: date,
    account: str = DEFAULT_ACCOUNT,
    max_results: int = _MAX_RESULTS,
) -> list[dict]:
    """Return Gmail message stubs (id + threadId) matching query since date.

    Paginated: a single Gmail page holds at most 100 messages, so a long
    look-back over a busy sender would otherwise be silently truncated.
    """
    headers = {"Authorization": f"Bearer {_token(account)}"}
    full_query = f"{query} after:{since.strftime('%Y/%m/%d')}"
    messages: list[dict] = []
    page_token: str | None = None

    while len(messages) < max_results:
        params = {
            "q": full_query,
            "maxResults": min(100, max_results - len(messages)),
        }
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(
            f"{_GMAIL_API}/messages", headers=headers, params=params, timeout=15
        )
        resp.raise_for_status()
        payload = resp.json()
        messages.extend(payload.get("messages", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return messages

    log.warning(
        "Gmail: query %r hit the %d-message cap — older results were dropped",
        query, max_results,
    )
    return messages


def get_message(msg_id: str, account: str = DEFAULT_ACCOUNT) -> dict:
    headers = {"Authorization": f"Bearer {_token(account)}"}
    resp = requests.get(
        f"{_GMAIL_API}/messages/{msg_id}",
        headers=headers,
        params={"format": "full"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_attachment_bytes(
    msg_id: str, attachment_id: str, account: str = DEFAULT_ACCOUNT
) -> bytes:
    headers = {"Authorization": f"Bearer {_token(account)}"}
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


def get_bodies(msg: dict) -> tuple[str, str]:
    """Return (html_body, text_body) of a message — either may be empty.

    Needed by providers whose invoice is the mail itself rather than an
    attachment; the body is then rendered to PDF (see providers.mail_pdf).
    """
    bodies: dict[str, str] = {}
    _collect_bodies(msg.get("payload", {}), bodies)
    return bodies.get("text/html", ""), bodies.get("text/plain", "")


def _collect_bodies(payload: dict, bodies: dict) -> None:
    mime = payload.get("mimeType", "")
    if mime in ("text/html", "text/plain") and not payload.get("filename"):
        data = payload.get("body", {}).get("data", "")
        if data and mime not in bodies:
            bodies[mime] = base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
    for part in payload.get("parts", []):
        _collect_bodies(part, bodies)


def get_header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def msg_date(msg: dict) -> date:
    ms = int(msg.get("internalDate", 0))
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
