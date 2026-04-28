from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from providers.base import Invoice


def _invoice(tmp_path) -> Invoice:
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    return Invoice(
        provider="ovh",
        invoice_id="INV-TEST",
        issue_date=date(2026, 3, 1),
        amount=42.00,
        currency="EUR",
        pdf_url=None,
        pdf_path=pdf,
    )


def test_send_invoice_calls_mailjet(tmp_path):
    inv = _invoice(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_send = MagicMock()
    mock_send.create.return_value = mock_response

    mock_client = MagicMock()
    mock_client.send = mock_send

    with patch("mailer._client", return_value=mock_client):
        import mailer
        mailer.send_invoice(inv)

    mock_send.create.assert_called_once()
    call_data = mock_send.create.call_args[1]["data"]
    msg = call_data["Messages"][0]
    assert msg["To"][0]["Email"] == "test-tiime@example.com"
    assert "OVH" in msg["Subject"]
    assert len(msg["Attachments"]) == 1
    assert msg["Attachments"][0]["Filename"] == "test.pdf"


def test_send_invoice_raises_on_mailjet_error(tmp_path):
    inv = _invoice(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.json.return_value = {"error": "server error"}

    mock_send = MagicMock()
    mock_send.create.return_value = mock_response

    mock_client = MagicMock()
    mock_client.send = mock_send

    with patch("mailer._client", return_value=mock_client):
        import mailer
        with pytest.raises(RuntimeError, match="Mailjet error 500"):
            mailer.send_invoice(inv)


def test_send_invoice_raises_when_no_pdf():
    inv = Invoice(
        provider="ovh",
        invoice_id="INV-NOPDF",
        issue_date=date(2026, 3, 1),
        amount=10.0,
        currency="EUR",
        pdf_url=None,
        pdf_path=None,
    )
    import mailer
    with pytest.raises(ValueError, match="PDF not found"):
        mailer.send_invoice(inv)
