"""Parsing for providers whose invoice is the mail body, not an attachment."""
from datetime import date
from email.message import EmailMessage

import pytest

from oauth2 import gmail_otp
from providers import imap_base, mail_parse, mail_pdf
from providers.youprice import _decode_stored_token, _parse_api_date


# ── IMAP message parsing (Pokawa) ──────────────────────────────────────────


def _raw_mail(*, html=None, text=None, pdf=None, subject="Votre commande Pokawa"):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "Pokawa <info@belorder.com>"
    msg["To"] = "y@nnick.com"
    msg["Date"] = "Thu, 6 Aug 2026 12:22:23 +0200"
    msg["Message-ID"] = "<abc123$def@belorder.com>"
    msg.set_content(text or "corps texte")
    if html:
        msg.add_alternative(html, subtype="html")
    if pdf:
        msg.add_attachment(
            pdf, maintype="application", subtype="pdf", filename="facture.pdf"
        )
    return msg.as_bytes()


def test_parse_message_extracts_bodies_and_metadata():
    parsed = imap_base.parse_message(
        _raw_mail(html="<p>Total : 17,10 €</p>", text="Total : 17,10 EUR")
    )
    assert parsed.sender == "info@belorder.com"
    assert parsed.subject == "Votre commande Pokawa"
    assert parsed.date == date(2026, 8, 6)
    assert "17,10" in parsed.html_body
    assert "17,10" in parsed.text_body
    assert parsed.pdf_attachments == []


def test_message_id_is_filename_safe_and_stable():
    parsed = imap_base.parse_message(_raw_mail(text="x"))
    assert parsed.message_id == "abc123_def@belorder.com"
    assert "<" not in parsed.message_id and "$" not in parsed.message_id


def test_message_id_falls_back_to_uid_when_header_missing():
    raw = b"From: info@belorder.com\r\nSubject: x\r\n\r\nbody\r\n"
    assert imap_base.parse_message(raw, fallback_id="42").message_id == "uid-42"


def test_pdf_attachment_is_collected_and_not_treated_as_body():
    parsed = imap_base.parse_message(_raw_mail(text="Total : 5,00 €", pdf=b"%PDF-1.4 fake"))
    assert len(parsed.pdf_attachments) == 1
    assert parsed.pdf_attachments[0]["filename"] == "facture.pdf"
    assert parsed.pdf_attachments[0]["content"].startswith(b"%PDF")
    assert "Total" in parsed.text_body


def test_body_text_falls_back_to_stripped_html():
    parsed = imap_base.parse_message(_raw_mail(html="<p>Total&nbsp;: 17,10&nbsp;&euro;</p>"))
    parsed.text_body = ""
    assert "17,10" in parsed.body_text
    assert "<p>" not in parsed.body_text


# ── Amount extraction ──────────────────────────────────────────────────────


# Real Pokawa receipt layout: every figure sits on the line *after* its label,
# and the first amount in the document is an item price, not the total.
_POKAWA_RECEIPT = """Le 17/07/2026 - Prévu pour 11h28
1x
Poké Création
16.40€
1x
Coca-Cola zéro
2.90€
Sous-total
19.30€
Total TTC
19.30€
Dont TVA 10%
1.49€
"""


@pytest.mark.parametrize("text,expected", [
    ("Total : 17,10 €", 17.10),
    ("Montant : 4,99 EUR", 4.99),
    ("€9.99 billed monthly", 9.99),
    ("Sous-total 12,00 €\nTotal 16,90 €", 16.90),
    ("Poke bowl 14,90 €\nBoisson 2,20 €\nTotal 17,10 €", 17.10),
    ("1 234,56 €", 1234.56),
    ("aucun montant ici", 0.0),
    (_POKAWA_RECEIPT, 19.30),
    # Label and figure on separate lines, no explicit "TTC"
    ("Total\n16,90 €\n", 16.90),
    # "Total TTC" outranks a bare "Total" seen earlier
    ("Total\n12,00 €\nTotal TTC\n19,30 €\n", 19.30),
    # A sub-total is never the charged amount, even on the following line
    ("Sous-total\n19,30 €\nTotal TTC\n21,30 €\n", 21.30),
    # An unrelated word containing "total" must not be treated as a label
    ("Remboursé totalement le 3 mars. Total : 8,00 €", 8.00),
])
def test_extract_amount_eur(text, expected):
    assert mail_parse.extract_amount_eur(text) == expected


def test_extract_reference():
    text = "Numéro de facture : BC84763201\nMerci"
    patterns = (r"num[ée]ro de facture\s*:?\s*([A-Z0-9-]+)",)
    assert mail_parse.extract_reference(text, patterns) == "BC84763201"
    assert mail_parse.extract_reference("rien", patterns) is None


# ── PDF rendering (document assembly, no browser) ──────────────────────────


def test_wrap_html_keeps_body_and_adds_traceability_header():
    doc = mail_pdf.wrap_html(
        "<p>Total : 17,10 €</p>", "info@belorder.com", "Commande", date(2026, 8, 6)
    )
    assert "<p>Total : 17,10 €</p>" in doc
    assert "info@belorder.com" in doc
    assert "2026-08-06" in doc


def test_wrap_text_escapes_the_body():
    doc = mail_pdf.wrap_text("a < b & c", "x@y.z", "Sujet", date(2026, 8, 6))
    assert "a &lt; b &amp; c" in doc


def test_mail_to_pdf_rejects_an_empty_mail(tmp_path):
    with pytest.raises(ValueError):
        mail_pdf.mail_to_pdf(
            tmp_path / "out.pdf",
            sender="x@y.z", subject="s", issue_date=date(2026, 8, 6),
        )


# ── OTP extraction ─────────────────────────────────────────────────────────


def test_youprice_otp_is_alphanumeric_and_survives_html_markup():
    body = gmail_otp._strip_html(
        "<p>Voici votre code de s&eacute;curit&eacute; unique :  <span>6XE8YY</span></p>"
    )
    assert gmail_otp._extract_code(body, gmail_otp.YOUPRICE_CODE) == "6XE8YY"
    # The historical 6-digit pattern cannot match it
    assert gmail_otp._extract_code(body, gmail_otp.DIGITS_6) is None


def test_starlink_otp_still_matches_six_digits():
    assert gmail_otp._extract_code("Your code is 481902.", gmail_otp.DIGITS_6) == "481902"


def test_youprice_otp_ignores_unrelated_six_char_words():
    assert gmail_otp._extract_code("Bonjour client fidele", gmail_otp.YOUPRICE_CODE) is None


# ── YouPrice API date parsing ──────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("2026-06-30T00:00:00", date(2026, 6, 30)),
    ("2025-12-31T00:00:00", date(2025, 12, 31)),
    ("2026-06-30", date(2026, 6, 30)),
    (None, None),
    ("", None),
    ("pas une date", None),
])
def test_parse_api_date(raw, expected):
    assert _parse_api_date(raw) == expected


def test_stored_token_is_json_decoded():
    # localStorage holds the token JSON-encoded; the quotes must not reach the API
    assert _decode_stored_token('"eyJhbGciOi.payload"') == "eyJhbGciOi.payload"
    assert _decode_stored_token("eyJhbGciOi.payload") == "eyJhbGciOi.payload"
    assert _decode_stored_token('  "eyJ.abc"  ') == "eyJ.abc"
