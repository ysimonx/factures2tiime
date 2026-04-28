from datetime import date

import pytest
import responses as responses_lib
import responses

from providers.scaleway import ScalewayProvider, _BASE


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("SCW_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SCW_ORG_ID", "test-org-id")
    import config
    import importlib
    importlib.reload(config)
    return ScalewayProvider()


@responses.activate
def test_list_invoices(provider):
    responses.add(
        responses.GET,
        f"{_BASE}/invoices",
        json={
            "invoices": [
                {
                    "id": "inv-abc123",
                    "issued_date": "2026-03-31T00:00:00Z",
                    "total_taxed": 99.50,
                    "billing_period": {"start_date": "2026-03-01", "end_date": "2026-03-31"},
                }
            ],
            "total_count": 1,
        },
        status=200,
    )
    invoices = provider.list_invoices(since=date(2026, 1, 1))
    assert len(invoices) == 1
    assert invoices[0].invoice_id == "inv-abc123"
    assert invoices[0].amount == 99.50
    assert invoices[0].issue_date == date(2026, 3, 31)


@responses.activate
def test_fetch_pdf(provider, tmp_path):
    import base64
    from providers.base import Invoice
    inv = Invoice(
        provider="scaleway",
        invoice_id="inv-abc123",
        issue_date=date(2026, 3, 31),
        amount=99.50,
        currency="EUR",
        pdf_url=None,
        pdf_path=None,
    )
    pdf_bytes = b"%PDF-1.4 scaleway"
    responses.add(
        responses.GET,
        f"{_BASE}/invoices/inv-abc123/download",
        json={
            "name": "invoice.pdf",
            "content_type": "application/pdf",
            "content": base64.b64encode(pdf_bytes).decode(),
        },
        status=200,
    )
    dest = provider.fetch_pdf(inv, tmp_path)
    assert dest.exists()
    assert dest.read_bytes() == pdf_bytes
    assert inv.pdf_path == dest


@responses.activate
def test_list_invoices_pagination(provider):
    responses.add(
        responses.GET,
        f"{_BASE}/invoices",
        json={
            "invoices": [{"id": f"inv-{i}", "issued_date": "2026-03-01", "total_taxed": 10.0}
                         for i in range(100)],
            "total_count": 150,
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{_BASE}/invoices",
        json={
            "invoices": [{"id": f"inv-{i}", "issued_date": "2026-03-01", "total_taxed": 10.0}
                         for i in range(100, 150)],
            "total_count": 150,
        },
        status=200,
    )
    invoices = provider.list_invoices(since=date(2026, 1, 1))
    assert len(invoices) == 150
