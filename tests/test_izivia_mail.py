"""Izivia invoices are billed by EDF business services, PDF always attached."""
from providers.izivia_mail import _invoice_number


def test_invoice_number_read_from_the_attachment_name():
    parts = [{"filename": "2026_00689901_08072026.pdf"}]
    assert _invoice_number(parts) == "00689901"


def test_siblings_of_the_same_day_keep_distinct_numbers():
    # Two invoices arrived on 2026-08-03; the number is what separates them
    a = _invoice_number([{"filename": "2026_00676826_08032026.pdf"}])
    b = _invoice_number([{"filename": "2026_00676716_08032026.pdf"}])
    assert a != b


def test_unexpected_name_yields_no_reference():
    assert _invoice_number([{"filename": "facture.pdf"}]) is None
    assert _invoice_number([{"filename": ""}]) is None
    assert _invoice_number([{}]) is None
    assert _invoice_number([]) is None


def test_first_matching_attachment_wins():
    parts = [{"filename": "logo.pdf"}, {"filename": "2026_00123456_01012026.pdf"}]
    assert _invoice_number(parts) == "00123456"
