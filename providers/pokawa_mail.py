from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import config
from providers import imap_base, mail_parse, mail_pdf
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# Pokawa receipts are plain emails — no PDF attached — sent by their ordering
# platform BelOrder to the personal (non-Gmail) mailbox. Sender in POKAWA_SENDER.


class PokawaMailProvider(InvoiceProvider):
    name = "pokawa_mail"

    def is_enabled(self) -> bool:
        return config.POKAWA_ENABLED and imap_base.is_configured()

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            messages = imap_base.fetch_messages(config.POKAWA_SENDER, since=since)
        except Exception as e:
            raise ProviderError(self.name, f"IMAP fetch failed: {e}")

        invoices = []
        for msg in messages:
            if msg.date < since:
                continue
            text = msg.body_text
            if not text and not msg.pdf_attachments:
                log.warning("Pokawa: message %s has no body, skipping", msg.message_id)
                continue
            invoices.append(Invoice(
                provider=self.name,
                invoice_id=msg.message_id,
                issue_date=msg.date,
                amount=mail_parse.extract_amount_eur(text),
                currency="EUR",
                pdf_url=None,
                pdf_path=None,
                # Bodies are kept for fetch_pdf so the run needs a single IMAP login
                raw={"message": msg},
            ))

        log.info("Pokawa: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        msg: imap_base.MailMessage | None = invoice.raw.get("message")
        if msg is None:
            raise ProviderError(
                self.name,
                f"No cached mail for {invoice.invoice_id} — re-run list_invoices()",
            )
        try:
            dest = dest_dir / f"pokawa_{invoice.issue_date}_{invoice.invoice_id[:40]}.pdf"

            # A PDF attachment, if it ever appears, beats rendering the body
            if msg.pdf_attachments:
                dest.write_bytes(msg.pdf_attachments[0]["content"])
            else:
                mail_pdf.mail_to_pdf(
                    dest,
                    sender=msg.sender or config.POKAWA_SENDER,
                    subject=msg.subject,
                    issue_date=msg.date,
                    html_body=msg.html_body,
                    text_body=msg.text_body,
                )

            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Render failed for {invoice.invoice_id}: {e}")
