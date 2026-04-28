from __future__ import annotations

import base64
import logging
import re
import time

import requests

import config
from oauth2 import refresher

log = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_starlink_otp(
    after_epoch: int | None = None,
    max_wait: int = 90,
    poll_interval: int = 5,
) -> str:
    """
    Poll Gmail for a Starlink verification code.
    after_epoch: only consider emails received after this Unix timestamp (int).
                 Defaults to now - 2 minutes if not provided.
    Raises TimeoutError if no code found within max_wait seconds.
    """
    if after_epoch is None:
        after_epoch = int(time.time()) - 120

    access_token = refresher.get_valid_token(
        provider="gmail",
        token_url=_TOKEN_URL,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
    )

    deadline = time.time() + max_wait
    while time.time() < deadline:
        code = _try_get_otp(access_token, after_epoch)
        if code:
            log.debug("Starlink OTP found: %s", code)
            return code
        log.debug("No OTP yet, waiting %ds…", poll_interval)
        time.sleep(poll_interval)

    raise TimeoutError(f"No Starlink OTP received within {max_wait}s")


def _try_get_otp(access_token: str, after_epoch: int) -> str | None:
    headers = {"Authorization": f"Bearer {access_token}"}
    # newer_than:3m gets recent emails; we filter precisely by internalDate below
    resp = requests.get(
        f"{_GMAIL_API}/messages",
        headers=headers,
        params={"q": "from:no-reply@starlink.com newer_than:5m", "maxResults": 10},
        timeout=15,
    )
    resp.raise_for_status()
    messages = resp.json().get("messages", [])
    if not messages:
        return None

    for msg_ref in messages:
        msg_resp = requests.get(
            f"{_GMAIL_API}/messages/{msg_ref['id']}",
            headers=headers,
            params={"format": "full"},
            timeout=15,
        )
        msg_resp.raise_for_status()
        msg = msg_resp.json()

        # internalDate is milliseconds since epoch — skip emails older than sign-in
        if int(msg.get("internalDate", 0)) / 1000 < after_epoch:
            continue

        code = _extract_code(_extract_body(msg))
        if code:
            return code

    return None


def _extract_body(msg: dict) -> str:
    return _decode_parts(msg.get("payload", {}))


def _decode_parts(payload: dict) -> str:
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        text = _decode_parts(part)
        if text:
            return text
    return ""


def _extract_code(text: str) -> str | None:
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None
