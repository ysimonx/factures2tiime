from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import config
from providers import gmail_base
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

# Subject: "Your payment has been processed for the invoice IN-EU-002-729-096"
_QUERY = 'from:atlassian.com subject:"Your payment has been processed" has:attachment filename:pdf'
_INVOICE_ID_RE = re.compile(r"\b(IN-[A-Z]{2}-\d{3}-\d{3}-\d{3})\b")


class AtlassianMailProvider(InvoiceProvider):
    name = "atlassian_mail"

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
                m = _INVOICE_ID_RE.search(subject)
                invoice_id = m.group(1) if m else msg_ref["id"]
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=invoice_id,
                    issue_date=bill_date,
                    amount=_extract_amount(subject),
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw={"msg_id": msg_ref["id"], "subject": subject},
                ))
            except Exception as e:
                log.warning("AtlassianMail: skipping message %s: %s", msg_ref["id"], e)

        log.info("AtlassianMail: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            msg_id = invoice.raw.get("msg_id", invoice.invoice_id)
            msg = gmail_base.get_message(msg_id)
            parts = gmail_base.find_pdf_parts(msg)
            if not parts:
                raise RuntimeError("No PDF attachment found in message")
            pdf_bytes = gmail_base.get_attachment_bytes(msg_id, parts[0]["attachment_id"])
            dest = dest_dir / f"atlassian_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(pdf_bytes)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")


def _extract_amount(subject: str) -> float:
    m = re.search(r"[€$£]\s*([\d.,]+)", subject)
    if m:
        return float(m.group(1).replace(",", "."))
    return 0.0
