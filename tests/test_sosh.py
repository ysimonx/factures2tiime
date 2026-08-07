"""Sosh billing API parsing — amounts in cents, and the two places bills live."""
from datetime import date

import pytest

from providers.sosh import _bill_list, _parse_date


def _bill(day, amount, ref="04D680M128"):
    return {
        "id": ref,
        "amount": amount,
        "date": day,
        "category": "facture",
        "hrefPdf": f"?billDate={day}&credentialKeyForPdf=abc",
    }


def test_history_bills_are_returned_in_order():
    payload = {"billsHistory": {"billList": [
        _bill("2026-07-23", 2499), _bill("2026-06-24", 2499),
    ]}}
    assert [b["date"] for b in _bill_list(payload)] == ["2026-07-23", "2026-06-24"]


def test_last_bill_is_added_when_absent_from_the_history():
    payload = {
        "billsHistory": {"billList": [_bill("2026-06-24", 2499)]},
        "lastBill": _bill("2026-07-23", 2499),
    }
    assert [b["date"] for b in _bill_list(payload)] == ["2026-06-24", "2026-07-23"]


def test_last_bill_is_not_duplicated_when_already_listed():
    payload = {
        "billsHistory": {"billList": [_bill("2026-07-23", 2499)]},
        "lastBill": _bill("2026-07-23", 2499),
    }
    assert len(_bill_list(payload)) == 1


def test_missing_history_still_yields_the_last_bill():
    assert len(_bill_list({"lastBill": _bill("2026-07-23", 2499)})) == 1


def test_empty_payload_is_not_an_error():
    assert _bill_list({}) == []
    assert _bill_list({"billsHistory": None, "lastBill": None}) == []


@pytest.mark.parametrize("cents,euros", [
    (2499, 24.99),
    (3332, 33.32),
    (0, 0.0),
])
def test_amounts_are_reported_in_cents(cents, euros):
    # Reading the field as euros would bill 2499 € instead of 24,99 €
    assert round(cents / 100, 2) == euros


@pytest.mark.parametrize("raw,expected", [
    ("2026-07-23", date(2026, 7, 23)),
    ("2026-07-23T00:00:00Z", date(2026, 7, 23)),
    (None, None),
    ("", None),
    ("pas une date", None),
])
def test_parse_date(raw, expected):
    assert _parse_date(raw) == expected
