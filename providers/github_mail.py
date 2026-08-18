from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import config
from providers import gmail_base, imap_base, mail_parse, mail_pdf
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# GitHub receipts land on the personal mailbox with the PDF attached. The
# subject is pinned because noreply@github.com also carries every notification,
# security alert and mention from the platform.
_QUERY = 'from:noreply@github.com subject:"Payment Receipt"'

# GitHub bills in dollars ("$4.00"); mail_parse only knows euros, so the dollar
# form is matched here. Comma thousands ("$1,234.00") appear on annual plans.
_USD = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})")
_REF_PATTERNS = (
    r"(?:receipt|invoice)\s*(?:number|no\.?|#)\s*:?\s*([A-Z0-9][A-Z0-9-]{3,})",
)


class GithubMailProvider(InvoiceProvider):
    name = "github_mail"

    @property
    def account(self) -> str:
        return config.GMAIL_PERSO_ACCOUNT

    def is_enabled(self) -> bool:
        return config.GITHUB_MAIL_ENABLED and gmail_base.has_account(self.account)

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            messages = gmail_base.search_messages(
                _QUERY, since=since, account=self.account
            )
        except Exception as e:
            raise ProviderError(self.name, f"Gmail search failed: {e}") from e

        invoices = []
        for msg_ref in messages:
            try:
                msg = gmail_base.get_message(msg_ref["id"], account=self.account)
                bill_date = gmail_base.msg_date(msg)
                if bill_date < since:
                    continue
                html_body, text_body = gmail_base.get_bodies(msg)
                text = text_body or imap_base.strip_html(html_body)
                amount, currency = _amount_and_currency(text)
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=msg_ref["id"],
                    issue_date=bill_date,
                    amount=amount,
                    currency=currency,
                    pdf_url=None,
                    pdf_path=None,
                    raw={
                        "msg_id": msg_ref["id"],
                        "subject": gmail_base.get_header(msg, "subject"),
                        "sender": gmail_base.get_header(msg, "from"),
                        "reference": mail_parse.extract_reference(
                            text, _REF_PATTERNS
                        ),
                    },
                ))
            except Exception as e:
                log.warning("GithubMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("GithubMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg_id = invoice.raw.get("msg_id", invoice.invoice_id)
            msg = gmail_base.get_message(msg_id, account=self.account)
            reference = invoice.raw.get("reference") or invoice.invoice_id
            dest = dest_dir / f"github_{invoice.issue_date}_{reference}.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)

            parts = gmail_base.find_pdf_parts(msg)
            if parts:
                dest.write_bytes(gmail_base.get_attachment_bytes(
                    msg_id, parts[0]["attachment_id"], account=self.account
                ))
            else:
                # Defensive: the receipt has always been attached, but a
                # body-only mail would otherwise abort the whole provider
                log.warning("GithubMail: no PDF on %s, rendering the body", msg_id)
                mail_pdf.mail_to_pdf(
                    dest,
                    sender=invoice.raw.get("sender") or "GitHub",
                    subject=invoice.raw.get("subject", ""),
                    issue_date=invoice.issue_date,
                    html_body=gmail_base.get_bodies(msg)[0],
                    text_body=gmail_base.get_bodies(msg)[1],
                )

            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(
                self.name, f"Download failed for {invoice.invoice_id}: {e}"
            ) from e


def _amount_and_currency(text: str) -> tuple[float, str]:
    """Charged amount and its currency, (0.0, "USD") when the body says nothing.

    Dollars are checked first — that is what GitHub, Inc. bills — and the euro
    path stays for a possible GitHub Europe invoice. An unknown amount is left
    at 0.0 so pdf_amount can read it from the attached receipt.
    """
    matches = _USD.findall(text)
    if matches:
        # Same convention as mail_parse: a receipt lists item prices before the
        # charged total, and the total is never smaller than its parts.
        return max(float(m.replace(",", "")) for m in matches), "USD"
    eur = mail_parse.extract_amount_eur(text)
    if eur:
        return eur, "EUR"
    return 0.0, "USD"
