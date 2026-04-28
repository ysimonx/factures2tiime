import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import config
from oauth2 import token_store
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
_BASE = "https://api.atlassian.com/commerce/api"
_PROVIDER = "atlassian"


class AtlassianProvider(InvoiceProvider):
    name = "atlassian"

    def is_enabled(self) -> bool:
        return all([
            config.ATLASSIAN_CLIENT_ID,
            config.ATLASSIAN_CLIENT_SECRET,
            config.ATLASSIAN_ACCOUNT_ID,
        ])

    def _get_token(self) -> str:
        data = token_store.load(_PROVIDER)
        if data and not token_store.is_expired(data):
            return data["access_token"]

        resp = requests.post(
            _TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": config.ATLASSIAN_CLIENT_ID,
                "client_secret": config.ATLASSIAN_CLIENT_SECRET,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.get("expires_in", 3600))
        token_store.save(
            provider=_PROVIDER,
            access_token=payload["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            scope=payload.get("scope"),
        )
        return payload["access_token"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-transaction-account": config.ATLASSIAN_ACCOUNT_ID,
        }

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            resp = requests.get(
                f"{_BASE}/v2/invoices",
                headers=self._headers(),
                params={"statusFilter": "PAID"},
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            raise ProviderError(self.name, f"Failed to list invoices: {e}")

        invoices = []
        for item in resp.json().get("data", []):
            raw_date = item.get("invoiceDate", "")[:10]
            try:
                bill_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if bill_date < since:
                continue
            invoices.append(Invoice(
                provider=self.name,
                invoice_id=item["id"],
                issue_date=bill_date,
                amount=float(item.get("totalAmount", 0)),
                currency=item.get("currency", "EUR"),
                pdf_url=None,
                pdf_path=None,
                raw=item,
            ))

        log.info("Atlassian: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        try:
            resp = requests.get(
                f"{_BASE}/v1/invoices/{invoice.invoice_id}/download",
                headers={**self._headers(), "Accept": "application/pdf"},
                params={"transactionAccountId": config.ATLASSIAN_ACCOUNT_ID},
                timeout=60,
            )
            resp.raise_for_status()
            dest = dest_dir / f"atlassian_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
