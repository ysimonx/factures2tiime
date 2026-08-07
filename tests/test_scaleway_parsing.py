"""Scaleway entries that are not billable documents must be skipped, not crash."""
from datetime import date

import pytest

from providers.scaleway import _extract_amount, _parse_item

_EUR = {"currency_code": "EUR", "units": 14, "nanos": 70000000}


def _item(**overrides) -> dict:
    item = {
        "id": "57dae311-0816-408e-873f-6cb0bf8ef107",
        "issued_date": "2026-06-01T00:00:00Z",
        "state": "paid",
        "total_taxed": _EUR,
    }
    item.update(overrides)
    return item


def test_parses_a_normal_invoice():
    inv = _parse_item(_item(), "scaleway")
    assert inv is not None
    assert inv.invoice_id == "57dae311-0816-408e-873f-6cb0bf8ef107"
    assert inv.issue_date == date(2026, 6, 1)
    assert inv.amount == pytest.approx(14.07)


def test_null_issued_date_is_skipped_not_raised():
    # The key exists with a null value, so .get(k, "") still returns None
    assert _parse_item(_item(issued_date=None, state="voided"), "scaleway") is None


def test_missing_issued_date_key_is_skipped():
    item = _item()
    del item["issued_date"]
    assert _parse_item(item, "scaleway") is None


def test_voided_invoice_is_skipped_even_when_dated():
    item = _item(state="voided", total_taxed={"units": 0, "nanos": 0})
    assert _parse_item(item, "scaleway") is None


def test_state_matching_is_case_insensitive():
    assert _parse_item(_item(state="VOIDED", issued_date=None), "scaleway") is None


def test_missing_state_is_still_parsed():
    item = _item()
    del item["state"]
    assert _parse_item(item, "scaleway") is not None


@pytest.mark.parametrize("value,expected", [
    ({"units": 14, "nanos": 70000000}, 14.07),
    ({"units": 0, "nanos": 0}, 0.0),
    ({"units": None, "nanos": None}, 0.0),
    (None, 0.0),
    (12.5, 12.5),
])
def test_extract_amount(value, expected):
    assert _extract_amount(value) == pytest.approx(expected)
