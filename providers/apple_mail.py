from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import config
from providers import gmail_base, imap_base, mail_parse, mail_pdf
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# Apple subscription receipts (Apple One, iCloud+, App Store) arrive on the
# personal mailbox as HTML — no PDF attached — from several apple.com senders
# (no_reply@, noreply@, EMEA_Invoicing@…), hence the domain-wide match. The
# subject is pinned because that mailbox also carries App Store Connect,
# TestFlight and marketing mail from the same domain.
_QUERY = (
    'from:apple.com '
    '{subject:"Votre reçu Apple" subject:"Your receipt from Apple"}'
)
_REF_PATTERNS = (
    r"(?:num[ée]ro de facture|invoice number)\s*:?\s*([A-Z0-9-]+)",
    r"(?:document\s*n[°o]|order id|identifiant de commande)\s*:?\s*([A-Z0-9-]+)",
)


class AppleMailProvider(InvoiceProvider):
    name = "apple_mail"

    @property
    def account(self) -> str:
        return config.GMAIL_PERSO_ACCOUNT

    def is_enabled(self) -> bool:
        return config.APPLE_MAIL_ENABLED and gmail_base.has_account(self.account)

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            messages = gmail_base.search_messages(_QUERY, since=since, account=self.account)
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
                if not (html_body or text_body or gmail_base.find_pdf_parts(msg)):
                    log.warning("AppleMail: message %s has no body, skipping", msg_ref["id"])
                    continue
                text = text_body or imap_base.strip_html(html_body)
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=msg_ref["id"],
                    issue_date=bill_date,
                    amount=mail_parse.extract_amount_eur(text),
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw={
                        "msg_id": msg_ref["id"],
                        "subject": gmail_base.get_header(msg, "subject"),
                        "sender": gmail_base.get_header(msg, "from"),
                        "reference": mail_parse.extract_reference(text, _REF_PATTERNS),
                    },
                ))
            except Exception as e:
                log.warning("AppleMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("AppleMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg_id = invoice.raw.get("msg_id", invoice.invoice_id)
            msg = gmail_base.get_message(msg_id, account=self.account)
            dest = dest_dir / f"apple_{invoice.issue_date}_{invoice.invoice_id}.pdf"

            parts = gmail_base.find_pdf_parts(msg)
            if parts:
                pdf_bytes = gmail_base.get_attachment_bytes(
                    msg_id, parts[0]["attachment_id"], account=self.account
                )
                dest.write_bytes(pdf_bytes)
            else:
                html_body, text_body = gmail_base.get_bodies(msg)
                mail_pdf.mail_to_pdf(
                    dest,
                    sender=invoice.raw.get("sender") or "Apple",
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
