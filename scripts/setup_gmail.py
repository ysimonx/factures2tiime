#!/usr/bin/env python3
from __future__ import annotations
"""
One-time Gmail OAuth2 authorization_code flow.
Run this once to store the refresh token in the local SQLite database.
The token is used to read Starlink OTP codes from yannick.simon@kysoe.com.

Usage:
  python scripts/setup_gmail.py

Prerequisites:
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth2 client ID (Desktop app type)
  3. Enable the Gmail API for the project
  4. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env
"""
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


def main():
    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET:
        print("Error: GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    storage.init_db()

    params = urlencode({
        "response_type": "code",
        "client_id": config.GMAIL_CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "login_hint": config.STARLINK_EMAIL or "",
    })
    auth_url = f"{_AUTH_URL}?{params}"

    server = HTTPServer(("localhost", _PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    print(f"\nOpening browser for Gmail authorization ({config.STARLINK_EMAIL})…")
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

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
    token_store.save(
        provider="gmail",
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope"),
    )
    print("Gmail tokens stored successfully.")


if __name__ == "__main__":
    main()
