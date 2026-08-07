from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import config
from providers import gmail_base, mail_pdf
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# Izivia (EV charging) bills through its parent, EDF business services, and the
# invoice always travels as a PDF attachment on the personal mailbox.
_QUERY = (
    'from:service-client@edf-bs.com '
    'subject:"Votre facture EDF business services est disponible"'
)
# Attachment names look like 2026_00689901_08072026.pdf — year, invoice no, MMDDYYYY
_INVOICE_NO = re.compile(r"^\d{4}_(\d+)_")


class IziviaMailProvider(InvoiceProvider):
    name = "izivia_mail"

    @property
    def account(self) -> str:
        return config.GMAIL_PERSO_ACCOUNT

    def is_enabled(self) -> bool:
        return config.IZIVIA_MAIL_ENABLED and gmail_base.has_account(self.account)

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
                parts = gmail_base.find_pdf_parts(msg)
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=msg_ref["id"],
                    issue_date=bill_date,
                    # The notification mail carries no total — only the PDF does
                    amount=0.0,
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw={
                        "msg_id": msg_ref["id"],
                        "subject": gmail_base.get_header(msg, "subject"),
                        "sender": gmail_base.get_header(msg, "from"),
                        "reference": _invoice_number(parts),
                    },
                ))
            except Exception as e:
                log.warning("IziviaMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("IziviaMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg_id = invoice.raw.get("msg_id", invoice.invoice_id)
            msg = gmail_base.get_message(msg_id, account=self.account)
            reference = invoice.raw.get("reference") or invoice.invoice_id
            dest = dest_dir / f"izivia_{invoice.issue_date}_{reference}.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)

            parts = gmail_base.find_pdf_parts(msg)
            if parts:
                dest.write_bytes(gmail_base.get_attachment_bytes(
                    msg_id, parts[0]["attachment_id"], account=self.account
                ))
            else:
                # Defensive: EDF has always attached the PDF, but a body-only
                # notification would otherwise abort the whole provider
                log.warning("IziviaMail: no PDF on %s, rendering the body", msg_id)
                html_body, text_body = gmail_base.get_bodies(msg)
                mail_pdf.mail_to_pdf(
                    dest,
                    sender=invoice.raw.get("sender") or "EDF business services",
                    subject=invoice.raw.get("subject", ""),
                    issue_date=invoice.issue_date,
                    html_body=html_body,
                    text_body=text_body,
                )

            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(
                self.name, f"Download failed for {invoice.invoice_id}: {e}"
            ) from e


def _invoice_number(parts: list[dict]) -> str | None:
    """Invoice number carried by the attachment name, when it follows the format."""
    for part in parts:
        m = _INVOICE_NO.match(part.get("filename") or "")
        if m:
            return m.group(1)
    return None
