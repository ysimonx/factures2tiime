import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_BILLING_BASE = "https://management.azure.com/providers/Microsoft.Billing"
_API_VERSION = "2024-04-01"


@dataclass
class _TenantConfig:
    label: str
    tenant_id: str
    client_id: str
    client_secret: str
    billing_account: str


class Microsoft365Provider(InvoiceProvider):
    name = "microsoft365"

    def __init__(self):
        self._tenants: list[_TenantConfig] = []
        if config.MS365_TENANT1_ID:
            self._tenants.append(_TenantConfig(
                label="tenant1",
                tenant_id=config.MS365_TENANT1_ID,
                client_id=config.MS365_TENANT1_CLIENT_ID,
                client_secret=config.MS365_TENANT1_SECRET,
                billing_account=config.MS365_TENANT1_BILLING_ACCOUNT,
            ))
        if config.MS365_TENANT2_ID:
            self._tenants.append(_TenantConfig(
                label="tenant2",
                tenant_id=config.MS365_TENANT2_ID,
                client_id=config.MS365_TENANT2_CLIENT_ID,
                client_secret=config.MS365_TENANT2_SECRET,
                billing_account=config.MS365_TENANT2_BILLING_ACCOUNT,
            ))

    def is_enabled(self) -> bool:
        return len(self._tenants) > 0

    def _get_token(self, tenant: _TenantConfig) -> str:
        resp = requests.post(
            _TOKEN_URL.format(tenant_id=tenant.tenant_id),
            data={
                "grant_type": "client_credentials",
                "client_id": tenant.client_id,
                "client_secret": tenant.client_secret,
                "scope": "https://management.azure.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _list_for_tenant(self, tenant: _TenantConfig, since: date, token: str) -> list[Invoice]:
        url = (
            f"{_BILLING_BASE}/billingAccounts/{tenant.billing_account}"
            f"/invoices?api-version={_API_VERSION}"
            f"&periodStartDate={since.isoformat()}&periodEndDate=9999-12-31"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()

        invoices = []
        for item in resp.json().get("value", []):
            props = item.get("properties", {})
            raw_date = props.get("invoiceDate", "")[:10]
            try:
                bill_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            amount = props.get("amountDue", {}).get("value", 0) or 0
            currency = props.get("amountDue", {}).get("currency", "EUR")
            invoices.append(Invoice(
                provider=f"{self.name}_{tenant.label}",
                invoice_id=item["name"],
                issue_date=bill_date,
                amount=float(amount),
                currency=currency,
                pdf_url=None,
                pdf_path=None,
                raw=item,
            ))
        return invoices

    def list_invoices(self, since: date) -> list[Invoice]:
        results = []
        for tenant in self._tenants:
            try:
                token = self._get_token(tenant)
                invoices = self._list_for_tenant(tenant, since, token)
                results.extend(invoices)
                log.info("Microsoft365 %s: %d invoice(s)", tenant.label, len(invoices))
            except Exception as e:
                raise ProviderError(self.name, f"Tenant {tenant.label}: {e}")
        return results

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        label = invoice.provider.replace(f"{self.name}_", "")
        tenant = next((t for t in self._tenants if t.label == label), None)
        if not tenant:
            raise ProviderError(self.name, f"Unknown tenant label: {label}")
        try:
            token = self._get_token(tenant)
            url = (
                f"{_BILLING_BASE}/billingAccounts/{tenant.billing_account}"
                f"/invoices/{invoice.invoice_id}/download"
                f"?api-version=2020-05-01"
            )
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
            )
            # Azure returns 202 with Location header for async download
            if resp.status_code == 202:
                location = resp.headers.get("Location")
                for _ in range(10):
                    time.sleep(3)
                    poll = requests.get(
                        location,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=30,
                    )
                    if poll.status_code == 200:
                        download_url = poll.json().get("url") or poll.json().get("downloadUrl")
                        if download_url:
                            pdf_resp = requests.get(download_url, timeout=60)
                            pdf_resp.raise_for_status()
                            dest = dest_dir / f"{invoice.provider}_{invoice.invoice_id}_{invoice.issue_date}.pdf"
                            dest.write_bytes(pdf_resp.content)
                            invoice.pdf_path = dest
                            return dest
                raise RuntimeError("Async download timed out")
            resp.raise_for_status()
            dest = dest_dir / f"{invoice.provider}_{invoice.invoice_id}_{invoice.issue_date}.pdf"
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")
