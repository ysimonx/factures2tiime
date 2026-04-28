import logging
from datetime import datetime, timedelta, timezone

import requests

from oauth2 import token_store

log = logging.getLogger(__name__)


class OAuthExpiredError(Exception):
    """Raised when the refresh token has expired and re-authorization is needed."""


def get_valid_token(
    provider: str,
    token_url: str,
    client_id: str,
    client_secret: str,
) -> str:
    """
    Return a valid access token for the given provider.
    Refreshes automatically if the stored token is about to expire.
    Raises OAuthExpiredError if refresh fails (refresh token expired).
    """
    data = token_store.load(provider)
    if not data:
        raise OAuthExpiredError(
            f"No stored token for {provider}. "
            f"Run scripts/setup_qonto.py to authorize."
        )

    if not token_store.is_expired(data):
        return data["access_token"]

    log.info("Refreshing access token for %s", provider)
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise OAuthExpiredError(f"No refresh token stored for {provider}.")

    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (400, 401):
            raise OAuthExpiredError(
                f"Refresh token expired for {provider}. "
                f"Re-run scripts/setup_qonto.py to re-authorize."
            ) from e
        raise

    payload = resp.json()
    expires_in = payload.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    token_store.save(
        provider=provider,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_at=expires_at,
        scope=payload.get("scope"),
    )
    log.info("Token refreshed for %s, expires at %s", provider, expires_at)
    return payload["access_token"]
