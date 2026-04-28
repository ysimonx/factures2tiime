from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from providers.ovh import OvhProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("OVH_APP_KEY", "ak")
    monkeypatch.setenv("OVH_APP_SECRET", "as")
    monkeypatch.setenv("OVH_CONSUMER_KEY", "ck")
    import config
    import importlib
    importlib.reload(config)
    return OvhProvider()


def _mock_client(bill_ids, bill_details):
    client = MagicMock()
    client.get.side_effect = lambda path: (
        bill_ids if path == "/me/bill" else bill_details.get(path.split("/")[-1], {})
    )
    return client


def test_list_invoices(provider):
    details = {
        "INV-2026-001": {
            "date": "2026-03-15",
            "priceWithTax": {"value": 24.99, "currencyCode": "EUR"},
            "pdfUrl": "https://ovh.com/invoice/INV-2026-001.pdf",
        }
    }
    mock_client = _mock_client(["INV-2026-001"], details)
    with patch.object(provider, "_client", return_value=mock_client):
        invoices = provider.list_invoices(since=date(2026, 1, 1))

    assert len(invoices) == 1
    assert invoices[0].invoice_id == "INV-2026-001"
    assert invoices[0].amount == 24.99
    assert invoices[0].issue_date == date(2026, 3, 15)


def test_list_invoices_filters_old(provider):
    details = {
        "INV-OLD": {
            "date": "2025-01-01",
            "priceWithTax": {"value": 5.0, "currencyCode": "EUR"},
            "pdfUrl": "https://ovh.com/invoice/INV-OLD.pdf",
        }
    }
    mock_client = _mock_client(["INV-OLD"], details)
    with patch.object(provider, "_client", return_value=mock_client):
        invoices = provider.list_invoices(since=date(2026, 1, 1))

    assert invoices == []


def test_fetch_pdf(provider, tmp_path):
    from providers.base import Invoice
    inv = Invoice(
        provider="ovh",
        invoice_id="INV-2026-001",
        issue_date=date(2026, 3, 15),
        amount=24.99,
        currency="EUR",
        pdf_url="https://ovh.com/invoice/INV-2026-001.pdf",
        pdf_path=None,
    )

    import responses as rsps_lib
    import responses

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, inv.pdf_url, body=b"%PDF-1.4 fake", status=200)
        dest = provider.fetch_pdf(inv, tmp_path)

    assert dest.exists()
    assert dest.read_bytes() == b"%PDF-1.4 fake"
    assert inv.pdf_path == dest
