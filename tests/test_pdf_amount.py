"""Reading an invoice total out of a PDF's text layer.

Every fixture below is the real text layer of an invoice this pipeline handles,
trimmed to the block that matters — pypdf flattens columns, and that flattening
is exactly what makes the naive readings wrong.
"""
from datetime import date

import pytest

from providers.base import Invoice
from providers.pdf_amount import amount_from_text, fill_amount

# Certigna states its totals with no currency sign at all: the unit lives in a
# column header ("Montants exprimés en Euros").
_CERTIGNA = """Désignation TVA P.U. HT Qté Total HT
20% 49,00 1 49,00
20% 21,50 1 21,50
Montants exprimés en Euros
Total HT 70,50
Total TVA 20% 14,10
Total TTC 84,60
"""

# Izivia stacks a column header over the line items, then the summary. The
# credit line makes the gross item larger than the invoice.
_IZIVIA_WITH_CREDIT = """Produit Montant HT Montant TTC
Formule ACCESS 11,67€ 14,00€
Crédit de Charge -6,00€ -7,20€
TVA (20 %)
1,13 €
Total HT
5,67 €
Total TTC
6,80 €
Montant payé 6,80 € TTC
"""

# Google puts every label first, then every figure, in reading order
_GOOGLE = """Sous-total en EUR
Total en EUR
8,10 €
1,62 €
9,72 €
"""

_MICROSOFT = """Montant total
EUR 13.64
Sous-total 11.37
Total (toutes taxes comprises) EUR 13.64
"""

_STARLINK = """Sous-total
29,17 €
Total TVA (20%)
5,83 €
Prix total
35,00 €
Total dû
35,00 €
"""


@pytest.mark.parametrize("text,expected", [
    (_CERTIGNA, 84.60),
    (_IZIVIA_WITH_CREDIT, 6.80),
    (_GOOGLE, 9.72),
    (_MICROSOFT, 13.64),
    (_STARLINK, 35.00),
])
def test_totals_of_real_invoices(text, expected):
    assert amount_from_text(text) == pytest.approx(expected)


def test_a_credit_line_must_not_inflate_the_total():
    """The gross item is 14,00 € but only 6,80 € was invoiced."""
    assert amount_from_text(_IZIVIA_WITH_CREDIT) == pytest.approx(6.80)


def test_sub_total_is_never_taken_for_the_total():
    # "Sous-total en EUR" contains a word boundary right before "total"
    assert amount_from_text("Sous-total en EUR\n8,10 €\n") is None


def test_amounts_excluding_tax_are_not_the_total():
    assert amount_from_text("Total HT 70,50\nTotal TVA 20% 14,10\n") is None


def test_a_date_is_not_an_amount():
    """"total du montant prélevé au 02.08.2026" must not yield 2,08."""
    assert amount_from_text("total du montant prélevé\nau 02.08.2026\n") is None


@pytest.mark.parametrize("text", [
    "Total TTC 1 234,56 €",
    "Total TTC 1.234,56 €",
])
def test_thousands_separators(text):
    assert amount_from_text(text) == pytest.approx(1234.56)


def test_absurd_values_are_rejected():
    assert amount_from_text("Total TTC 999999999,00 €") is None


def test_no_label_means_unknown_rather_than_a_guess():
    assert amount_from_text("Facture\n42,00 €\nMerci") is None
    assert amount_from_text("") is None


# ── fill_amount ────────────────────────────────────────────────────────────


def _invoice(amount=0.0, pdf_path=None):
    return Invoice(
        provider="alan_mail", invoice_id="X1", issue_date=date(2026, 8, 1),
        amount=amount, currency="EUR", pdf_url=None, pdf_path=pdf_path,
    )


def test_an_amount_known_by_the_provider_is_never_overwritten(tmp_path):
    inv = _invoice(amount=24.99, pdf_path=tmp_path / "x.pdf")
    assert fill_amount(inv) is False
    assert inv.amount == 24.99


def test_nothing_to_do_without_a_pdf():
    assert fill_amount(_invoice()) is False


def test_unreadable_pdf_leaves_the_amount_unset(tmp_path):
    # An OVH download once stored an HTML error page under a .pdf name
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"<!DOCTYPE html><html>error</html>")
    inv = _invoice(pdf_path=broken)
    assert fill_amount(inv) is False
    assert inv.amount == 0.0
