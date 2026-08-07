"""
Shared Qonto Business API plumbing.

Authentication is OAuth2 when a token has been stored (scripts/setup_qonto.py),
falling back to the historical `login:secret_key` API-key header. Both providers
(`qonto`, `qonto_attachments`) go through here so the mode is decided in one place.
"""
from __future__ import annotations

import logging
from datetime import date

import requests

import config
from oauth2 import refresher, token_store

log = logging.getLogger(__name__)

BASE = "https://thirdparty.qonto.com/v2"
_TOKEN_URL = "https://oauth.qonto.com/oauth2/token"
_PER_PAGE = 100


class QontoAuthError(RuntimeError):
    pass


def has_oauth() -> bool:
    return bool(
        config.QONTO_CLIENT_ID
        and config.QONTO_CLIENT_SECRET
        and token_store.load("qonto")
    )


def has_api_key() -> bool:
    return bool(config.QONTO_LOGIN and config.QONTO_SECRET_KEY)


def is_configured() -> bool:
    return has_oauth() or has_api_key()


def auth_headers() -> dict:
    if has_oauth():
        token = refresher.get_valid_token(
            provider="qonto",
            token_url=_TOKEN_URL,
            client_id=config.QONTO_CLIENT_ID,
            client_secret=config.QONTO_CLIENT_SECRET,
        )
        return {"Authorization": f"Bearer {token}"}
    if has_api_key():
        return {"Authorization": f"{config.QONTO_LOGIN}:{config.QONTO_SECRET_KEY}"}
    raise QontoAuthError(
        "No Qonto credentials. Run scripts/setup_qonto.py (OAuth) "
        "or set QONTO_LOGIN / QONTO_SECRET_KEY."
    )


def _get(
    path: str,
    # A list of pairs, not a dict, so repeated keys like status[] survive
    params: dict | list[tuple[str, object]] | None = None,
    timeout: int = 30,
) -> dict:
    resp = requests.get(
        f"{BASE}/{path}", headers=auth_headers(), params=params, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()


def bank_account_ids() -> list[str]:
    """UUIDs of the organization's bank accounts — transactions are per account."""
    org = _get("organization").get("organization", {})
    ids = [a["id"] for a in org.get("bank_accounts", []) if a.get("id")]
    if not ids:
        raise QontoAuthError("No bank account returned by /v2/organization")
    log.debug("Qonto: %d bank account(s)", len(ids))
    return ids


def list_transactions_with_attachments(since: date) -> list[dict]:
    """Debit transactions carrying at least one attachment.

    Filtering is on `emitted_at`, not `settled_at`: a card payment stays
    `pending` with a null `settled_at` for one to three days, so a receipt
    scanned the same day would be invisible on both counts. `declined` is left
    out — those never become an expense.

    `with_attachments` and `includes[]=attachments` do the filtering server-side
    and inline the file metadata, so no per-transaction round trip is needed.
    """
    transactions: list[dict] = []

    for account_id in bank_account_ids():
        page = 1
        while True:
            data = _get("transactions", [
                ("bank_account_id", account_id),
                ("emitted_at_from", f"{since.isoformat()}T00:00:00.000Z"),
                ("status[]", "completed"),
                ("status[]", "pending"),
                ("side", "debit"),
                ("with_attachments", "true"),
                ("includes[]", "attachments"),
                ("sort_by", "emitted_at:desc"),
                ("page", page),
                ("per_page", _PER_PAGE),
            ])
            batch = data.get("transactions") or []
            transactions.extend(batch)

            meta = data.get("meta") or {}
            next_page = meta.get("next_page")
            if not batch or not next_page:
                break
            page = next_page

    log.debug("Qonto: %d transaction(s) with attachments", len(transactions))
    return transactions


def transaction_attachments(transaction_id: str) -> list[dict]:
    """Fresh attachment descriptors — download URLs expire after 30 minutes."""
    data = _get(f"transactions/{transaction_id}/attachments", timeout=60)
    return data.get("attachments") or []


def download(url: str) -> bytes:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content
