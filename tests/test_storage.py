from datetime import date
from pathlib import Path

import storage
from providers.base import Invoice


def _invoice(provider="ovh", invoice_id="INV-001"):
    return Invoice(
        provider=provider,
        invoice_id=invoice_id,
        issue_date=date(2026, 3, 1),
        amount=12.50,
        currency="EUR",
        pdf_url="https://example.com/inv.pdf",
        pdf_path=None,
    )


def test_record_and_dedup():
    inv = _invoice()
    storage.record_invoice(inv)
    assert storage.already_sent("ovh", "INV-001")
    # Second insert should be ignored (UNIQUE constraint)
    storage.record_invoice(inv)
    with storage.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as n FROM sent_invoices WHERE provider='ovh'")
        assert cur.fetchone()["n"] == 1


def test_not_yet_sent():
    assert not storage.already_sent("ovh", "INV-MISSING")


def test_update_pdf_path(tmp_path):
    inv = _invoice()
    storage.record_invoice(inv)
    inv.pdf_path = tmp_path / "inv.pdf"
    storage.update_pdf_path(inv)
    with storage.db_cursor() as cur:
        cur.execute("SELECT pdf_path FROM sent_invoices WHERE invoice_id='INV-001'")
        assert cur.fetchone()["pdf_path"] == str(inv.pdf_path)


def test_mark_sent(tmp_path):
    inv = _invoice()
    storage.record_invoice(inv)
    inv.pdf_path = tmp_path / "inv.pdf"
    inv.pdf_path.write_bytes(b"%PDF fake")
    storage.update_pdf_path(inv)
    storage.mark_sent(inv, "tiime@example.com")
    with storage.db_cursor() as cur:
        cur.execute("SELECT emailed_at, email_to FROM sent_invoices WHERE invoice_id='INV-001'")
        row = cur.fetchone()
        assert row["emailed_at"] is not None
        assert row["email_to"] == "tiime@example.com"


def test_get_unsent(tmp_path):
    inv = _invoice()
    storage.record_invoice(inv)
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF fake")
    inv.pdf_path = pdf
    storage.update_pdf_path(inv)
    unsent = storage.get_unsent()
    assert len(unsent) == 1
    assert unsent[0]["invoice_id"] == "INV-001"


def test_run_log():
    run_id = storage.start_run()
    assert run_id > 0
    storage.finish_run(run_id, "success", ["ovh"], [], 2, 2)
    with storage.db_cursor() as cur:
        cur.execute("SELECT * FROM run_log WHERE id=?", (run_id,))
        row = cur.fetchone()
        assert row["status"] == "success"
        assert row["invoices_sent"] == 2
