"""Shared text extraction for providers whose invoice lives in the mail body."""
from __future__ import annotations

import re

# "17,10 €" / "€17.10" / "EUR 17,10" / "17.10 EUR"
_AMOUNT = r"(\d{1,3}(?:[  ]?\d{3})*(?:[.,]\d{2})?)"
_AFTER = re.compile(_AMOUNT + r"\s*(?:€|EUR\b)", re.IGNORECASE)
_BEFORE = re.compile(r"(?:€|EUR\b)\s*" + _AMOUNT, re.IGNORECASE)
# Ordered alternation: the longer, more specific labels must win at a given
# position. "Sous-total"/"Subtotal" are matched only to be discarded — they
# contain "total" but are never the charged amount.
_TOTAL_LABEL = re.compile(
    r"(?i)\b(sous[-\s]?total|subtotal|total\s*ttc|montant\s*total"
    r"|amount\s+charged|total|montant)\b"
)
_STRONG_LABELS = ("total ttc", "montant total", "amount charged")
# Receipts often put the figure on the line *after* its label, so the search
# window deliberately crosses newlines.
_AMOUNT_WINDOW = 60


def extract_amount_eur(text: str) -> float:
    """Best-effort amount in euros, 0.0 when nothing convincing is found.

    A labelled total wins over the first amount in the document, so a receipt
    listing item prices still reports the charged total. An explicit "Total TTC"
    beats a bare "Total", and the last occurrence beats earlier ones.
    """
    strong: list[float] = []
    weak: list[float] = []

    for m in _TOTAL_LABEL.finditer(text):
        label = " ".join(m.group(1).lower().split())
        if label.startswith(("sous", "sub")):
            continue
        amount = _first_amount(text[m.end():m.end() + _AMOUNT_WINDOW])
        if amount is None:
            continue
        (strong if label in _STRONG_LABELS else weak).append(amount)

    if strong:
        return strong[-1]
    if weak:
        return weak[-1]
    amount = _first_amount(text)
    return amount if amount is not None else 0.0


def _first_amount(text: str) -> float | None:
    for pattern in (_AFTER, _BEFORE):
        m = pattern.search(text)
        if m:
            return _to_float(m.group(1))
    return None


def _to_float(raw: str) -> float | None:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    # Thousands separator, not a decimal point: 1.234 → 1234
    if cleaned.count(".") > 1:
        head, _, tail = cleaned.rpartition(".")
        cleaned = head.replace(".", "") + "." + tail
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_reference(text: str, patterns: tuple[str, ...]) -> str | None:
    """First capture group matching any of `patterns`, else None."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return (m.group(1) if m.groups() else m.group(0)).strip()
    return None
