"""
Read the invoice total out of a PDF.

Most mail providers only ever forwarded an attachment, so they recorded no
amount at all. The figure exists only inside the document, hence this pass —
run once the PDF is on disk, and only when the provider left the amount empty.

Text-layer PDFs only: a scanned image yields nothing, and that is reported as
"unknown" rather than guessed, so a wrong total never reaches the accountant.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# The total sits on the first page of nearly every invoice; scanning further
# mostly picks up terms and conditions.
_MAX_PAGES = 3

# Only labels that unambiguously mean "including tax". A bare "Total" is
# rejected on purpose: it also matches "Total HT" and "Total TVA", which would
# understate the invoice.
# The negative lookbehinds matter: "Sous-total en EUR" contains a word boundary
# right before "total", so without them a sub-total would pass as the total.
# "Montant TTC" is deliberately absent: it is a column *header*, and its window
# spans the line items — on an invoice carrying a credit line, that reads the
# gross item instead of the discounted total and overstates the invoice.
_TTC_LABEL = re.compile(
    r"(?i)(?<!sous-)(?<!sous )(?<!sub)\b(?:"
    r"total\s*t\.?t\.?c"
    r"|total\s*\(?\s*toutes\s*taxes[^)\n]*\)?"
    r"|total\s*[àa]\s*(?:payer|r[ée]gler)|net\s*[àa]\s*payer"
    r"|montant\s*(?:pay[ée]|pr[ée]lev[ée]|d[ûu]|total)"
    r"|prix\s*total|total\s*d[ûu]|total\s*(?:en\s*)?(?:EUR|euros?)"
    r"|amount\s*(?:due|paid|charged)|total\s*due|total\s*amount"
    r")\b"
)
# Amounts in an invoice's text layer often carry no currency sign — it lives in
# a column header — so two decimals are the only thing that makes a number an
# amount. The word boundary stops "2026129,00" being read out of glued text.
# The trailing guard rejects a number that continues with another separator and
# digits — "02.08.2026" would otherwise be read as the amount 2,08.
_AMOUNT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  .]\d{3})*|\d+)[.,](\d{2})(?!\d|[.,/-]\d)"
)
# A figure explicitly marked as excluding tax must never be taken for the total
_HT_NEARBY = re.compile(r"(?i)\b(?:h\.?t\.?|hors\s*taxes?)\b")
_WINDOW = 60
# Sanity bound: this pipeline handles subscriptions, not property deals
_MAX_PLAUSIBLE = 100_000.0


def extract_text(path: Path, max_pages: int = _MAX_PAGES) -> str:
    """Text layer of the first pages, or "" when the PDF has none."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        log.warning("pypdf is not installed — amounts cannot be read from PDFs")
        return ""

    try:
        reader = PdfReader(str(path))
        pages = reader.pages[:max_pages]
        return "\n".join((page.extract_text() or "") for page in pages)
    except Exception as e:
        log.warning("Cannot read text from %s: %s", path.name, e)
        return ""


def amount_from_text(text: str) -> float | None:
    """Largest figure attached to an "including tax" label, or None.

    The largest wins because an invoice repeats its TTC total in several places
    — a column header, the summary line, the payment notice — and the smaller
    matches are per-line prices sitting under a header of the same name.
    """
    candidates: list[float] = []
    for m in _TTC_LABEL.finditer(text):
        window = text[m.end():m.end() + _WINDOW]
        # Invoices often stack the labels first and the figures after, so the
        # nearest number can be the sub-total. The total is the largest of the
        # block: sub-total and VAT are, by construction, parts of it.
        values = [
            v for found in _AMOUNT.finditer(window)
            if (v := _to_float(found)) is not None and 0 < v <= _MAX_PLAUSIBLE
        ]
        if values:
            candidates.append(max(values))

    if not candidates:
        return None
    return max(candidates)


def _to_float(match: re.Match) -> float | None:
    integer = re.sub(r"[  .]", "", match.group(1))
    try:
        return float(f"{integer}.{match.group(2)}")
    except ValueError:
        return None


def amount_from_pdf(path: Path) -> float | None:
    """Invoice total in euros, or None when the PDF does not say."""
    if not path or not Path(path).exists():
        return None
    text = extract_text(Path(path))
    if not text.strip():
        log.debug("%s has no text layer (scanned image?)", Path(path).name)
        return None
    return amount_from_text(text)


def fill_amount(invoice) -> bool:
    """Set `invoice.amount` from its PDF when the provider left it empty.

    Returns True when a figure was found. Never overwrites an amount the
    provider already knows — those come from an API and are authoritative.
    """
    if invoice.amount:
        return False
    if not invoice.pdf_path:
        return False
    amount = amount_from_pdf(Path(invoice.pdf_path))
    if amount is None:
        log.info(
            "No amount found in %s/%s — left unspecified",
            invoice.provider, invoice.invoice_id,
        )
        return False
    invoice.amount = amount
    log.info(
        "Amount read from PDF for %s/%s: %.2f %s",
        invoice.provider, invoice.invoice_id, amount, invoice.currency,
    )
    return True
