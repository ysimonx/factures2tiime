#!/usr/bin/env python3
from __future__ import annotations
"""
One-time Qonto OAuth2 authorization_code flow.
Run this once to store the refresh token in the local SQLite database.

Usage:
  python scripts/setup_qonto.py
"""
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from datetime import datetime, timedelta, timezone

import config
import storage
from oauth2 import token_store

_AUTH_URL = "https://oauth.qonto.com/oauth2/auth"
_TOKEN_URL = "https://oauth.qonto.com/oauth2/token"
_REDIRECT_URI = config.QONTO_REDIRECT_URI or "http://localhost:8080/callback"
_PORT = int(_REDIRECT_URI.split(":")[-1].split("/")[0])

_auth_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        qs = parse_qs(urlparse(self.path).query)
        _auth_code = qs.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authorization received. You can close this tab.")

    def log_message(self, *args):
        pass


def main():
    if not config.QONTO_CLIENT_ID or not config.QONTO_CLIENT_SECRET:
        print("Error: QONTO_CLIENT_ID and QONTO_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    storage.init_db()

    params = urlencode({
        "response_type": "code",
        "client_id": config.QONTO_CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "scope": "offline_access client_invoices.read",
    })
    auth_url = f"{_AUTH_URL}?{params}"

    server = HTTPServer(("localhost", _PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    print(f"\nOpening browser for Qonto authorization...\n{auth_url}\n")
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
            "client_id": config.QONTO_CLIENT_ID,
            "client_secret": config.QONTO_CLIENT_SECRET,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
    token_store.save(
        provider="qonto",
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope"),
    )
    print("Qonto tokens stored successfully.")
    print(f"Refresh token expires in ~90 days. Re-run this script before then if needed.")


if __name__ == "__main__":
    main()
