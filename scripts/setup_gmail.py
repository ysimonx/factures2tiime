#!/usr/bin/env python3
from __future__ import annotations
"""
One-time Gmail OAuth2 authorization_code flow.
Run this once per mailbox to store the refresh token in the local SQLite database.
The main account is used for Starlink/YouPrice OTP codes and the pro invoices;
a secondary account holds personal invoices (Apple receipts…).

Usage:
  python scripts/setup_gmail.py                        # main account ("gmail")
  python scripts/setup_gmail.py --account gmail_perso  # secondary mailbox

Prerequisites:
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth2 client ID (Desktop app type)
  3. Enable the Gmail API for the project
  4. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env
"""
import argparse
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

import config
import storage
from oauth2 import token_store

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_REDIRECT_URI = config.GMAIL_REDIRECT_URI
_PORT = int(_REDIRECT_URI.split(":")[-1].split("/")[0])

_auth_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        qs = parse_qs(urlparse(self.path).query)
        _auth_code = qs.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gmail authorization received. You can close this tab.")

    def log_message(self, *args):
        pass


def _mailbox_address(access_token: str) -> str:
    """The address Google actually granted, whatever was picked in the browser."""
    resp = requests.get(
        _PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("emailAddress", "")


def _expected_address(account: str, requested: str | None) -> str:
    """Address this alias should map to: explicit flag, then what is already
    stored for the alias, then the historical default for the main mailbox."""
    if requested:
        return requested
    stored = token_store.load(account) or {}
    if stored.get("account_email"):
        return stored["account_email"]
    return config.STARLINK_EMAIL if account == "gmail" else ""


def main():
    parser = argparse.ArgumentParser(description="Authorize a Gmail mailbox")
    parser.add_argument(
        "--account",
        default="gmail",
        help='Token store key for this mailbox (default: "gmail")',
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Address to pre-fill on the Google consent screen",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Store the token even if the authorized mailbox differs from the "
             "one this alias already points at (use when moving an alias)",
    )
    args = parser.parse_args()

    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        print("Error: GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    storage.init_db()

    login_hint = _expected_address(args.account, args.email)
    params = urlencode({
        "response_type": "code",
        "client_id": config.GMAIL_CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "login_hint": login_hint or "",
    })
    auth_url = f"{_AUTH_URL}?{params}"

    server = HTTPServer(("localhost", _PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    print(f"\nOpening browser for Gmail authorization "
          f"(account={args.account}, {login_hint or 'choose in browser'})…")
    print(f"URL: {auth_url}\n")
    webbrowser.open(auth_url)
    thread.join(timeout=120)

    if not _auth_code:
        print("No authorization code received. Aborting.")
        sys.exit(1)

    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "redirect_uri": _REDIRECT_URI,
            "client_id": config.GMAIL_CLIENT_ID,
            "client_secret": config.GMAIL_CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()

    # Which mailbox did Google actually authorize? The consent screen ignores
    # login_hint when the browser is already signed in elsewhere, so a token can
    # silently land on the wrong alias — check before writing anything.
    authorized_email = _mailbox_address(payload["access_token"])
    print(f"Authorized mailbox: {authorized_email}")

    if (login_hint and authorized_email
            and authorized_email.lower() != login_hint.lower() and not args.force):
        print(
            f"\nRefusing to store: account '{args.account}' points at {login_hint}, "
            f"but authorization was granted for {authorized_email}.\n"
            f"Re-run and pick the right account on the Google consent screen "
            f"(sign out of the other one first), or pass --force to move "
            f"'{args.account}' to {authorized_email}."
        )
        sys.exit(1)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
    token_store.save(
        provider=args.account,
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope"),
        account_email=authorized_email or None,
    )
    print(f"Gmail tokens stored successfully for account '{args.account}' "
          f"({authorized_email}).")


if __name__ == "__main__":
    main()
