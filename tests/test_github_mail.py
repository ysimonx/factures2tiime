"""GitHub payment receipts: dollar amounts, references, mailbox wiring."""
from datetime import date

import pytest

from providers import mail_parse
from providers.github_mail import _REF_PATTERNS, _amount_and_currency


def test_dollar_receipt_reads_the_charged_total():
    text = (
        "GITHUB RECEIPT - ysimonx\n"
        "GitHub Copilot Pro  $10.00\n"
        "Total  $10.00\n"
    )
    assert _amount_and_currency(text) == (10.00, "USD")


def test_item_prices_never_beat_the_total():
    text = "Seat 1  $4.00\nSeat 2  $4.00\nTotal charged  $8.00\n"
    assert _amount_and_currency(text) == (8.00, "USD")


def test_annual_plan_with_thousands_separator():
    assert _amount_and_currency("Total  $1,234.00") == (1234.00, "USD")


def test_a_euro_receipt_stays_in_euros():
    assert _amount_and_currency("Montant total : 9,80 €") == (9.80, "EUR")


def test_silent_body_defers_to_the_pdf():
    # 0.0 lets pdf_amount.fill_amount read the figure from the attachment
    assert _amount_and_currency("Thanks for your business!") == (0.0, "USD")


@pytest.mark.parametrize("text,expected", [
    ("Receipt #ABC1234-0042", "ABC1234-0042"),
    ("Invoice number: 20260801-XYZ", "20260801-XYZ"),
    ("Receipt no. RCPT-0099", "RCPT-0099"),
    ("no reference here", None),
])
def test_reference_extraction(text, expected):
    assert mail_parse.extract_reference(text, _REF_PATTERNS) == expected


def test_provider_is_registered():
    from providers.github_mail import GithubMailProvider
    assert GithubMailProvider.name == "github_mail"


def test_disabled_without_env_flag(monkeypatch):
    import config
    from providers.github_mail import GithubMailProvider
    monkeypatch.setattr(config, "GITHUB_MAIL_ENABLED", False)
    assert GithubMailProvider().is_enabled() is False
