from __future__ import annotations

import base64
import html
import logging
import re
import time

import requests

import config
from oauth2 import refresher

log = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


# Starlink sends 6 digits; YouPrice sends 6 uppercase alphanumerics (e.g. 6XE8YY),
# which only the surrounding sentence tells apart from ordinary words.
DIGITS_6 = r"\b(\d{6})\b"
YOUPRICE_CODE = r"(?i:code de s[ée]curit[ée] unique\s*:?\s*)([A-Z0-9]{6})\b"


def get_otp(
    sender: str,
    *,
    pattern: str = DIGITS_6,
    label: str = "OTP",
    after_epoch: int | None = None,
    max_wait: int = 90,
    poll_interval: int = 5,
    account: str = "gmail",
) -> str:
    """
    Poll Gmail for a one-time code sent by `sender`, matched by `pattern`.
    after_epoch: only consider emails received after this Unix timestamp (int).
                 Defaults to now - 2 minutes if not provided.
    Raises TimeoutError if no code found within max_wait seconds.
    """
    if after_epoch is None:
        after_epoch = int(time.time()) - 120

    access_token = refresher.get_valid_token(
        provider=account,
        token_url=_TOKEN_URL,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
    )

    deadline = time.time() + max_wait
    seen: set[str] = set()
    while time.time() < deadline:
        try:
            code = _try_get_otp(access_token, after_epoch, sender, pattern, seen)
        except requests.RequestException as e:
            log.warning("%s: Gmail poll failed (%s), retrying…", label, e)
            code = None
        if code:
            log.debug("%s found: %s", label, code)
            return code
        log.debug("No %s yet, waiting %ds…", label, poll_interval)
        time.sleep(poll_interval)

    raise TimeoutError(f"No {label} received within {max_wait}s")


def get_starlink_otp(
    after_epoch: int | None = None,
    max_wait: int = 90,
    poll_interval: int = 5,
) -> str:
    return get_otp(
        "no-reply@starlink.com",
        pattern=DIGITS_6,
        label="Starlink OTP",
        after_epoch=after_epoch,
        max_wait=max_wait,
        poll_interval=poll_interval,
    )


def get_youprice_otp(
    after_epoch: int | None = None,
    max_wait: int = 120,
    poll_interval: int = 5,
) -> str:
    return get_otp(
        "noreply@youprice.fr",
        pattern=YOUPRICE_CODE,
        label="YouPrice OTP",
        after_epoch=after_epoch,
        max_wait=max_wait,
        poll_interval=poll_interval,
    )


def _try_get_otp(
    access_token: str, after_epoch: int, sender: str, pattern: str,
    seen: set[str],
) -> str | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    # Deliberately no `q=` search: Gmail's search index can lag several minutes
    # behind delivery, which starves a two-minute OTP window (bitten by YouPrice
    # on 2026-08-08). A plain recency listing sees new mail immediately; the
    # sender is filtered client-side on the From header instead.
    resp = requests.get(
        f"{_GMAIL_API}/messages",
        headers=headers,
        params={"maxResults": 20, "includeSpamTrash": "true"},
        timeout=15,
    )
    resp.raise_for_status()

    for msg_ref in resp.json().get("messages", []):
        if msg_ref["id"] in seen:
            continue
        msg_resp = requests.get(
            f"{_GMAIL_API}/messages/{msg_ref['id']}",
            headers=headers,
            params={"format": "full"},
            timeout=15,
        )
        msg_resp.raise_for_status()
        msg = msg_resp.json()
        # Remember only successfully fetched messages, so a failed fetch is
        # retried on the next poll
        seen.add(msg_ref["id"])

        # internalDate is milliseconds since epoch — skip emails older than sign-in
        if int(msg.get("internalDate", 0)) / 1000 < after_epoch:
            continue
        if sender.lower() not in _from_header(msg).lower():
            continue

        code = _extract_code(_extract_body(msg), pattern)
        if code:
            return code

    return None


def _from_header(msg: dict) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == "from":
            return h.get("value") or ""
    return ""


def _extract_body(msg: dict) -> str:
    """All text parts concatenated, HTML stripped.

    Codes can live in either alternative, and YouPrice wraps its code in a
    <span> — matching against raw markup would miss it.
    """
    parts: list[str] = []
    _decode_parts(msg.get("payload", {}), parts)
    return "\n".join(_strip_html(p) for p in parts)


def _decode_parts(payload: dict, parts: list[str]) -> None:
    data = payload.get("body", {}).get("data", "")
    if data:
        parts.append(
            base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        )
    for part in payload.get("parts", []):
        _decode_parts(part, parts)


def _strip_html(text: str) -> str:
    if "<" not in text:
        return text
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\xa0]+", " ", html.unescape(text))


def _extract_code(text: str, pattern: str = DIGITS_6) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None
