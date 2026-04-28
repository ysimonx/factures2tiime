from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from providers import gmail_base
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# Subject: "Alan - Facture du mois de mars"
_QUERY = 'from:alan.eu subject:"Alan - Facture" has:attachment filename:pdf'
_MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}


class AlanMailProvider(InvoiceProvider):
    name = "alan_mail"

    def is_enabled(self) -> bool:
        return gmail_base.is_gmail_configured()

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            messages = gmail_base.search_messages(_QUERY, since=since)
        except Exception as e:
            raise ProviderError(self.name, f"Gmail search failed: {e}")

        invoices = []
        for msg_ref in messages:
            try:
                msg = gmail_base.get_message(msg_ref["id"])
                if not gmail_base.find_pdf_parts(msg):
                    continue
                bill_date = gmail_base.msg_date(msg)
                if bill_date < since:
                    continue
                subject = gmail_base.get_header(msg, "subject")
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=msg_ref["id"],
                    issue_date=bill_date,
                    amount=0.0,
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw={"msg_id": msg_ref["id"], "subject": subject},
                ))
            except Exception as e:
                log.warning("AlanMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("AlanMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg_id = invoice.raw.get("msg_id", invoice.invoice_id)
            msg = gmail_base.get_message(msg_id)
            parts = gmail_base.find_pdf_parts(msg)
            if not parts:
                raise RuntimeError("No PDF attachment found in message")
            pdf_bytes = gmail_base.get_attachment_bytes(msg_id, parts[0]["attachment_id"])
            dest = dest_dir / f"alan_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(pdf_bytes)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
