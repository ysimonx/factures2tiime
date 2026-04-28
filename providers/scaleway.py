import base64
import logging
from datetime import date
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_BASE = "https://api.scaleway.com/billing/v2beta1"


def _extract_amount(val) -> float:
    if isinstance(val, dict):
        units = float(val.get("units") or 0)
        nanos = float(val.get("nanos") or 0)
        return units + nanos / 1e9
    return float(val or 0)


class ScalewayProvider(InvoiceProvider):
    name = "scaleway"

    def is_enabled(self) -> bool:
        return bool(config.SCW_AUTH_TOKEN and config.SCW_ORG_ID)

    def _headers(self) -> dict:
        return {"X-Auth-Token": config.SCW_AUTH_TOKEN}

    def list_invoices(self, since: date) -> list[Invoice]:
        invoices = []
        page = 1
        while True:
            try:
                resp = requests.get(
                    f"{_BASE}/invoices",
                    headers=self._headers(),
                    params={
                        "organization_id": config.SCW_ORG_ID,
                        "billing_period_start_after": since.isoformat() + "T00:00:00Z",
                        "page": page,
                        "page_size": 100,
                        "order_by": "issued_date_desc",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
            except Exception as e:
                raise ProviderError(self.name, f"Failed to list invoices: {e}")

            data = resp.json()
            items = data.get("invoices", [])
            for item in items:
                issued = item.get("issued_date", "")[:10]
                try:
                    bill_date = date.fromisoformat(issued)
                except ValueError:
                    continue
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=item["id"],
                    issue_date=bill_date,
                    amount=_extract_amount(item.get("total_taxed", 0)),
                    currency="EUR",
                    pdf_url=None,
                    pdf_path=None,
                    raw=item,
                ))

            total = data.get("total_count", 0)
            if page * 100 >= total:
                break
            page += 1

        log.info("Scaleway: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            resp = requests.get(
                f"{_BASE}/invoices/{invoice.invoice_id}/download",
                headers=self._headers(),
                params={"file_type": "pdf"},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            pdf_bytes = base64.b64decode(data["content"])
            dest = dest_dir / f"scaleway_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(pdf_bytes)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
