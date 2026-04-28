#!/usr/bin/env python3
from __future__ import annotations
"""
Reset sent_invoices for a given provider and optional month.

Usage:
  python scripts/reset_state.py ovh
  python scripts/reset_state.py scaleway 2026-03
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import storage


def reset(provider: str, month: str | None = None) -> None:
    storage.init_db()
    with storage.db_cursor() as cur:
        if month:
            cur.execute(
                "DELETE FROM sent_invoices WHERE provider=? AND issue_date LIKE ?",
                (provider, f"{month}%"),
            )
            print(f"Deleted invoices for provider={provider!r}, month={month!r} ({cur.rowcount} rows)")
        else:
            cur.execute("DELETE FROM sent_invoices WHERE provider=?", (provider,))
            print(f"Deleted all invoices for provider={provider!r} ({cur.rowcount} rows)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_state.py <provider> [YYYY-MM]")
        sys.exit(1)
    provider = sys.argv[1]
    month = sys.argv[2] if len(sys.argv) > 2 else None
    reset(provider, month)
