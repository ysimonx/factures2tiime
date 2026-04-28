from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import config
from providers import gmail_base
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_QUERY = "from:no-reply@starlink.com has:attachment filename:pdf"


class StarlinkMailProvider(InvoiceProvider):
    name = "starlink_mail"

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
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=msg_ref["id"],
                    issue_date=bill_date,
                    amount=_extract_amount(msg),
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw={"msg_id": msg_ref["id"]},
                ))
            except Exception as e:
                log.warning("StarlinkMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("StarlinkMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg = gmail_base.get_message(invoice.invoice_id)
            parts = gmail_base.find_pdf_parts(msg)
            if not parts:
                raise RuntimeError("No PDF attachment found in message")
            pdf_bytes = gmail_base.get_attachment_bytes(
                invoice.invoice_id, parts[0]["attachment_id"]
            )
            dest = dest_dir / f"starlink_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(pdf_bytes)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")


def _extract_amount(msg: dict) -> float:
    subject = gmail_base.get_header(msg, "subject")
    m = re.search(r"€\s*([\d.,]+)", subject)
    if m:
        return float(m.group(1).replace(",", "."))
    return 0.0
