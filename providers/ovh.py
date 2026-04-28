import logging
from datetime import date
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)


class OvhProvider(InvoiceProvider):
    name = "ovh"

    def is_enabled(self) -> bool:
        return all([config.OVH_APP_KEY, config.OVH_APP_SECRET, config.OVH_CONSUMER_KEY])

    def _client(self):
        import ovh
        return ovh.Client(
            endpoint=config.OVH_ENDPOINT,
            application_key=config.OVH_APP_KEY,
            application_secret=config.OVH_APP_SECRET,
            consumer_key=config.OVH_CONSUMER_KEY,
        )

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            client = self._client()
            bill_ids: list[str] = client.get("/me/bill")
        except Exception as e:
            raise ProviderError(self.name, f"Failed to list bills: {e}")

        invoices = []
        for bill_id in bill_ids:
            try:
                detail = client.get(f"/me/bill/{bill_id}")
                bill_date = date.fromisoformat(detail["date"][:10])
                if bill_date < since:
                    continue
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=bill_id,
                    issue_date=bill_date,
                    amount=float(detail.get("priceWithTax", {}).get("value", 0)),
                    currency=detail.get("priceWithTax", {}).get("currencyCode", "EUR"),
                    pdf_url=detail.get("pdfUrl"),
                    pdf_path=None,
                    raw=detail,
                ))
            except Exception as e:
                log.warning("Skipping bill %s: %s", bill_id, e)

        log.info("OVH: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        if not invoice.pdf_url:
            raise ProviderError(self.name, f"No pdfUrl for {invoice.invoice_id}")
        try:
            import ovh
            client = self._client()
            # OVH pdfUrl requires authenticated request via the SDK
            resp = requests.get(invoice.pdf_url, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            dest = dest_dir / f"ovh_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
