import logging
from datetime import date
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_BASE = "https://api.infomaniak.com/1"


class InfomaniakProvider(InvoiceProvider):
    name = "infomaniak"

    def is_enabled(self) -> bool:
        return bool(config.INFOMANIAK_API_TOKEN and config.INFOMANIAK_ACCOUNT_ID)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {config.INFOMANIAK_API_TOKEN}"}

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            resp = requests.get(
                f"{_BASE}/invoicing/{config.INFOMANIAK_ACCOUNT_ID}/invoice/list",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            raise ProviderError(self.name, f"Failed to list invoices: {e}")

        invoices = []
        for item in resp.json().get("data", []):
            raw_date = item.get("date", "")[:10]
            try:
                bill_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if bill_date < since:
                continue
            invoices.append(Invoice(
                provider=self.name,
                invoice_id=str(item["id"]),
                issue_date=bill_date,
                amount=float(item.get("total", 0)),
                currency=item.get("currency", "CHF"),
                pdf_url=None,
                pdf_path=None,
                raw=item,
            ))

        log.info("Infomaniak: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            resp = requests.get(
                f"{_BASE}/invoicing/{config.INFOMANIAK_ACCOUNT_ID}/invoice/{invoice.invoice_id}/pdf",
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()
            dest = dest_dir / f"infomaniak_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
