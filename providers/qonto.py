import logging
from datetime import date
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_BASE = "https://thirdparty.qonto.com/v2"


class QontoProvider(InvoiceProvider):
    name = "qonto"

    def is_enabled(self) -> bool:
        return bool(config.QONTO_LOGIN and config.QONTO_SECRET_KEY)

    def _headers(self) -> dict:
        return {"Authorization": f"{config.QONTO_LOGIN}:{config.QONTO_SECRET_KEY}"}

    def list_invoices(self, since: date) -> list[Invoice]:
        invoices = []
        try:
            resp = requests.get(
                f"{_BASE}/client_invoices",
                headers=self._headers(),
                params={
                    "created_at_from": since.isoformat(),
                    "sort": "created_at:desc",
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            raise ProviderError(self.name, f"Failed to list invoices: {e}")

        for item in resp.json().get("client_invoices", []):
            raw_date = (item.get("issue_date") or item.get("created_at", ""))[:10]
            try:
                bill_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            invoices.append(Invoice(
                provider=self.name,
                invoice_id=item["id"],
                issue_date=bill_date,
                amount=float(item.get("total_amount", 0)),
                currency=item.get("currency", "EUR"),
                pdf_url=item.get("attachment", {}).get("url"),
                pdf_path=None,
                raw=item,
            ))

        log.info("Qonto: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        if not invoice.pdf_url:
            raise ProviderError(self.name, f"No attachment URL for {invoice.invoice_id}")
        try:
            resp = requests.get(
                invoice.pdf_url,
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()
            dest = dest_dir / f"qonto_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
