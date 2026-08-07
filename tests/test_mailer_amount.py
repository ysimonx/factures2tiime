"""What reaches the accountant: the amount wording, and the attachment guard."""
from datetime import date

import pytest

import mailer
from providers.base import Invoice


def _sent(monkeypatch, amount, tmp_path, content=b"%PDF-1.4 fake"):
    pdf = tmp_path / "facture.pdf"
    pdf.write_bytes(content)
    inv = Invoice(
        provider="alan_mail", invoice_id="X1", issue_date=date(2026, 8, 1),
        amount=amount, currency="EUR", pdf_url=None, pdf_path=pdf,
    )

    captured = {}

    class _Result:
        status_code = 200

        def json(self):
            return {}

    class _Send:
        def create(self, data):
            captured.update(data)
            return _Result()

    class _Client:
        send = _Send()

    monkeypatch.setattr(mailer, "_client", lambda: _Client())
    mailer.send_invoice(inv)
    message = captured["Messages"][0]
    return message["Subject"], message["TextPart"]


def test_a_known_amount_is_stated(monkeypatch, tmp_path):
    subject, body = _sent(monkeypatch, 129.00, tmp_path)
    assert "129.00 EUR" in subject
    assert "Montant     : 129.00 EUR" in body


def test_an_unknown_amount_is_left_out_of_the_subject(monkeypatch, tmp_path):
    subject, body = _sent(monkeypatch, 0.0, tmp_path)
    assert "0.00" not in subject
    assert "EUR" not in subject
    assert subject.endswith("Facture 2026-08")
    # The body says so explicitly rather than printing a wrong figure
    assert "0.00" not in body
    assert "non déterminé" in body


def test_a_non_pdf_attachment_is_refused(monkeypatch, tmp_path):
    """An OVH download once stored an HTML error page and it was forwarded."""
    with pytest.raises(ValueError, match="is not a PDF"):
        _sent(monkeypatch, 12.0, tmp_path, content=b"<!DOCTYPE html><html>oops")
