from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import config
from providers.base import Invoice

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_invoices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    invoice_id  TEXT NOT NULL,
    issue_date  TEXT NOT NULL,
    amount      REAL,
    currency    TEXT,
    pdf_path    TEXT,
    emailed_at  TEXT,
    email_to    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider, invoice_id)
);
CREATE INDEX IF NOT EXISTS idx_si_provider ON sent_invoices(provider);
CREATE INDEX IF NOT EXISTS idx_si_date     ON sent_invoices(issue_date);

CREATE TABLE IF NOT EXISTS run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT,
    providers_ok    TEXT,
    providers_err   TEXT,
    invoices_new    INTEGER DEFAULT 0,
    invoices_sent   INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS oauth2_tokens (
    provider        TEXT PRIMARY KEY,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    expires_at      TEXT,
    scope           TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        cur.executescript(_SCHEMA)


@contextmanager
def db_cursor():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def already_sent(provider: str, invoice_id: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sent_invoices WHERE provider=? AND invoice_id=?",
            (provider, invoice_id),
        )
        return cur.fetchone() is not None


def record_invoice(inv: Invoice) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT OR IGNORE INTO sent_invoices
               (provider, invoice_id, issue_date, amount, currency)
               VALUES (?, ?, ?, ?, ?)""",
            (inv.provider, inv.invoice_id, inv.issue_date.isoformat(),
             inv.amount, inv.currency),
        )


def update_pdf_path(inv: Invoice) -> None:
    with db_cursor() as cur:
        cur.execute(
            "UPDATE sent_invoices SET pdf_path=? WHERE provider=? AND invoice_id=?",
            (str(inv.pdf_path), inv.provider, inv.invoice_id),
        )


def mark_sent(inv: Invoice, email_to: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE sent_invoices
               SET emailed_at=datetime('now'), email_to=?
               WHERE provider=? AND invoice_id=?""",
            (email_to, inv.provider, inv.invoice_id),
        )


def get_unsent() -> list[sqlite3.Row]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM sent_invoices WHERE emailed_at IS NULL AND pdf_path IS NOT NULL"
        )
        return cur.fetchall()


def start_run() -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO run_log (started_at) VALUES (datetime('now'))"
        )
        return cur.lastrowid


def finish_run(
    run_id: int,
    status: str,
    providers_ok: list[str],
    providers_err: list[str],
    invoices_new: int,
    invoices_sent: int,
    error_message: str | None = None,
) -> None:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE run_log SET
               finished_at=datetime('now'), status=?,
               providers_ok=?, providers_err=?,
               invoices_new=?, invoices_sent=?, error_message=?
               WHERE id=?""",
            (
                status,
                json.dumps(providers_ok),
                json.dumps(providers_err),
                invoices_new,
                invoices_sent,
                error_message,
                run_id,
            ),
        )
