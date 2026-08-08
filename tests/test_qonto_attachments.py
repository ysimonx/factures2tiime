"""Qonto transaction receipts: merchant filtering, dates, and file naming."""
from datetime import date

import pytest

import config
from providers.qonto_attachments import (
    QontoAttachmentsProvider,
    _details,
    _is_covered_elsewhere,
    _looks_like_image,
    _merchant,
    _payment,
    _settled_date,
    _slug,
    _vat,
)


def _tx(tx_id, merchant, attachment_ids, settled="2026-08-04T10:00:00.000Z"):
    return {
        "id": tx_id,
        "clean_counterparty_name": merchant,
        "settled_at": settled,
        "amount": 8.20,
        "currency": "EUR",
        "attachments": [{"id": a, "file_name": f"{a}.jpeg"} for a in attachment_ids],
    }


def test_an_attachment_shared_by_two_transactions_is_listed_once(monkeypatch):
    # A monthly invoice can be filed against several fee transactions
    shared = "019d48aa-794a-7e34-9f0c-5650d6f98d71"
    monkeypatch.setattr(
        "providers.qonto_base.list_transactions_with_attachments",
        lambda since: [_tx("tx-1", "Qonto", [shared]), _tx("tx-2", "Qonto", [shared])],
    )
    invoices = QontoAttachmentsProvider().list_invoices(date(2026, 1, 1))
    assert [i.invoice_id for i in invoices] == [shared]


def test_distinct_attachments_are_all_kept(monkeypatch):
    ids = ["0198f0da-8fd0-71aa-9ea9-da47b6ad2ca1",
           "0198f0da-fe04-7d75-9bc9-de9345702baa"]
    monkeypatch.setattr(
        "providers.qonto_base.list_transactions_with_attachments",
        lambda since: [_tx("tx-1", "MR SARKISSIAN", ids)],
    )
    invoices = QontoAttachmentsProvider().list_invoices(date(2026, 1, 1))
    assert sorted(i.invoice_id for i in invoices) == sorted(ids)


def test_filenames_stay_distinct_for_uuidv7_siblings():
    """UUIDv7 ids share a timestamp prefix — truncating them loses a receipt."""
    ids = ["0198f0da-8fd0-71aa-9ea9-da47b6ad2ca1",
           "0198f0da-fe04-7d75-9bc9-de9345702baa"]
    assert ids[0][:8] == ids[1][:8], "premise: the prefixes really do collide"
    names = {f"qonto_2025-08-29_mr-sarkissian_{i}.pdf" for i in ids}
    assert len(names) == 2


def test_merchant_prefers_the_cleaned_counterparty_name():
    tx = {"clean_counterparty_name": "Pokawa", "label": "POKAWA 13480 CABRIES CB"}
    assert _merchant(tx) == "Pokawa"


def test_merchant_falls_back_to_the_raw_label():
    assert _merchant({"label": "LE PETIT BISTROT"}) == "LE PETIT BISTROT"
    assert _merchant({}) == ""


@pytest.mark.parametrize("merchant,covered", [
    ("OVH", True),
    ("ovh sas", True),
    ("Scaleway", True),
    ("APPLE.COM/BILL", True),
    ("Pokawa", True),
    ("Le Petit Bistrot", False),
    ("Five Guys", False),
    ("Ibis Budget", False),
    ("", False),
])
def test_merchants_already_collected_elsewhere_are_skipped(merchant, covered):
    assert _is_covered_elsewhere(merchant) is covered


def test_skip_list_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "QONTO_ATTACHMENTS_SKIP", ["bistrot"])
    assert _is_covered_elsewhere("Le Petit Bistrot") is True
    assert _is_covered_elsewhere("OVH") is False


@pytest.mark.parametrize("raw,expected", [
    ("2026-08-06T10:22:23.000Z", date(2026, 8, 6)),
    ("2026-08-06T00:30:00.000+02:00", date(2026, 8, 5)),  # UTC-normalised
    (None, None),
    ("pas une date", None),
])
def test_settled_date(raw, expected):
    assert _settled_date({"settled_at": raw}) == expected


def test_settled_date_falls_back_to_emitted_at():
    """A card payment stays pending with a null settled_at for a few days."""
    tx = {"settled_at": None, "emitted_at": "2026-07-17T09:28:28.000Z"}
    assert _settled_date(tx) == date(2026, 7, 17)


def test_a_pending_receipt_scanned_today_is_collected(monkeypatch):
    # Regression: filtering on settled_at + status=completed hid same-day scans
    pending = {
        "id": "tx-carrefour",
        "clean_counterparty_name": "Carrefour Market",
        "status": "pending",
        "settled_at": None,
        "emitted_at": "2026-08-07T11:00:00.000Z",
        "amount": 29.17,
        "currency": "EUR",
        "attachments": [{"id": "att-1", "file_name": "ticket.jpeg"}],
    }
    monkeypatch.setattr(
        "providers.qonto_base.list_transactions_with_attachments",
        lambda since: [pending],
    )
    invoices = QontoAttachmentsProvider().list_invoices(date(2026, 8, 1))
    assert len(invoices) == 1
    assert invoices[0].issue_date == date(2026, 8, 7)
    assert invoices[0].amount == pytest.approx(29.17)


@pytest.mark.parametrize("merchant,expected", [
    ("Le Petit Bistrot", "le-petit-bistrot"),
    ("POKAWA 13480 CABRIÈS CB", "pokawa-13480-cabri-s-cb"),
    ("", "transaction"),
    ("!!!", "transaction"),
])
def test_slug_is_filename_safe(merchant, expected):
    slug = _slug(merchant)
    assert slug == expected
    assert "/" not in slug and " " not in slug


def test_slug_is_bounded():
    assert len(_slug("A" * 200)) <= 30


@pytest.mark.parametrize("content,is_image", [
    (b"\xff\xd8\xff\xe0 jpeg", True),
    (b"\x89PNG\r\n\x1a\n rest", True),
    (b"%PDF-1.4 ...", False),
    (b"", False),
])
def test_image_sniffing(content, is_image):
    assert _looks_like_image(content) is is_image


# ── Transaction context forwarded to the accountant ────────────────────────


def test_invoices_carry_the_merchant_and_transaction_details(monkeypatch):
    tx = _tx("tx-1", "Le Petit Bistrot", ["att-1"])
    tx.update(
        transaction_id="acme-corp-1234",
        operation_type="card",
        card_last_digits="4321",
        vat_amount=1.37,
        vat_rate=10.0,
    )
    monkeypatch.setattr(
        "providers.qonto_base.list_transactions_with_attachments",
        lambda since: [tx],
    )
    (inv,) = QontoAttachmentsProvider().list_invoices(date(2026, 1, 1))
    assert inv.label == "Le Petit Bistrot"
    assert inv.details["Marchand"] == "Le Petit Bistrot"
    assert inv.details["Transaction"] == "acme-corp-1234"
    assert inv.details["Paiement"] == "Carte ****4321"
    assert inv.details["TVA"] == "1.37 EUR (10 %)"


def test_details_keep_the_raw_statement_label_when_cleaned(monkeypatch):
    tx = {
        "clean_counterparty_name": "Pokawa",
        "label": "POKAWA 13480 CABRIES CB",
        "note": "déjeuner client",
        "category": "restaurant_and_bar",
    }
    details = _details(tx, _merchant(tx))
    assert details["Libellé"] == "POKAWA 13480 CABRIES CB"
    assert details["Note"] == "déjeuner client"
    assert details["Catégorie"] == "restaurant and bar"


def test_details_omit_a_label_identical_to_the_merchant():
    tx = {"label": "LE PETIT BISTROT"}
    assert "Libellé" not in _details(tx, "LE PETIT BISTROT")


def test_details_spell_out_a_foreign_currency_amount():
    tx = {"currency": "EUR", "local_currency": "USD", "local_amount": -12.5}
    assert _details(tx, "")["Montant local"] == "12.50 USD"


def test_details_skip_local_amount_in_the_billing_currency():
    tx = {"currency": "EUR", "local_currency": "EUR", "local_amount": 8.2}
    assert "Montant local" not in _details(tx, "")


@pytest.mark.parametrize("tx,expected", [
    ({"operation_type": "card", "card_last_digits": "1234"}, "Carte ****1234"),
    ({"operation_type": "card"}, "Carte"),
    ({"operation_type": "transfer"}, "Virement"),
    ({"operation_type": "direct_debit"}, "Prélèvement"),
    ({"operation_type": "pagopa_payment"}, "pagopa_payment"),  # unknown: as-is
    ({}, None),
])
def test_payment_label(tx, expected):
    assert _payment(tx) == expected


@pytest.mark.parametrize("tx,expected", [
    ({"vat_amount": 8.33, "vat_rate": 20.0, "currency": "EUR"}, "8.33 EUR (20 %)"),
    # -1 means several rates on one receipt — the total is still exact
    ({"vat_amount": 3.10, "vat_rate": -1, "currency": "EUR"}, "3.10 EUR"),
    ({"vat_amount": -1.37, "vat_rate": 10.0, "currency": "EUR"}, "1.37 EUR (10 %)"),
    ({"vat_amount": None}, None),
    ({}, None),
])
def test_vat_formatting(tx, expected):
    assert _vat(tx) == expected
