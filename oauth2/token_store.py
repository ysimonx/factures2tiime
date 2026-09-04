from __future__ import annotations

from datetime import datetime, timezone

import storage


def load(provider: str) -> dict | None:
    with storage.db_cursor() as cur:
        cur.execute(
            "SELECT access_token, refresh_token, expires_at, scope, account_email "
            "FROM oauth2_tokens WHERE provider=?",
            (provider,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "expires_at": row["expires_at"],
            "scope": row["scope"],
            "account_email": row["account_email"],
        }


def save(provider: str, access_token: str, refresh_token: str | None,
         expires_at: datetime | None, scope: str | None = None,
         account_email: str | None = None) -> None:
    """Store a token for `provider`.

    `account_email` identifies the mailbox behind the alias — it is only known
    right after an authorization_code flow, so a plain refresh passes None and
    the stored value is kept (COALESCE) rather than wiped.
    """
    expires_str = expires_at.isoformat() if expires_at else None
    with storage.db_cursor() as cur:
        cur.execute(
            """INSERT INTO oauth2_tokens
                 (provider, access_token, refresh_token, expires_at, scope, account_email)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET
                 access_token=excluded.access_token,
                 refresh_token=excluded.refresh_token,
                 expires_at=excluded.expires_at,
                 scope=excluded.scope,
                 account_email=COALESCE(excluded.account_email, oauth2_tokens.account_email),
                 updated_at=datetime('now')""",
            (provider, access_token, refresh_token, expires_str, scope, account_email),
        )


def is_expired(token_data: dict, margin_seconds: int = 300) -> bool:
    expires_at = token_data.get("expires_at")
    if not expires_at:
        return False
    exp = datetime.fromisoformat(expires_at)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc).timestamp() + margin_seconds >= exp.timestamp()
