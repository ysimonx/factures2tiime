import logging
from datetime import date
from pathlib import Path

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_LOGIN_URL = "https://mobile.free.fr/account/v2/login"


class FreeMobileProvider(InvoiceProvider):
    name = "free_mobile"

    def is_enabled(self) -> bool:
        return config.FREE_MOBILE_ENABLED and bool(config.FREE_MOBILE_USER and config.FREE_MOBILE_PASS)

    def list_invoices(self, since: date) -> list[Invoice]:
        from playwright.sync_api import sync_playwright
        invoices = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(_LOGIN_URL)
                page.fill("input[name='login']", config.FREE_MOBILE_USER)
                page.fill("input[name='pass']", config.FREE_MOBILE_PASS)
                page.click("button[type='submit']")
                page.wait_for_load_state("networkidle")

                # Navigate to invoices section
                page.goto("https://mobile.free.fr/account/v2/conso")
                page.wait_for_load_state("networkidle")

                invoice_links = page.query_selector_all("a[href*='facture']")
                for link in invoice_links:
                    href = link.get_attribute("href")
                    text = link.inner_text()
                    if not href:
                        continue
                    # Extract date from link text (format varies)
                    try:
                        bill_date = _parse_date_from_text(text)
                    except ValueError:
                        continue
                    if bill_date < since:
                        continue
                    invoices.append(Invoice(
                        provider=self.name,
                        invoice_id=href.split("/")[-1] or text,
                        issue_date=bill_date,
                        amount=0.0,
                        currency="EUR",
                        pdf_url=href if href.startswith("http") else f"https://mobile.free.fr{href}",
                        pdf_path=None,
                    ))
                browser.close()
        except Exception as e:
            raise ProviderError(self.name, f"Scraping failed: {e}")

        log.info("Free Mobile: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(_LOGIN_URL)
                page.fill("input[name='login']", config.FREE_MOBILE_USER)
                page.fill("input[name='pass']", config.FREE_MOBILE_PASS)
                page.click("button[type='submit']")
                page.wait_for_load_state("networkidle")

                with page.expect_download() as dl_info:
                    page.goto(invoice.pdf_url)
                download = dl_info.value
                dest = dest_dir / f"free_mobile_{invoice.invoice_id}_{invoice.issue_date}.pdf"
                download.save_as(dest)
                browser.close()
                invoice.pdf_path = dest
                return dest
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")


def _parse_date_from_text(text: str) -> date:
    import re
    months_fr = {
        "janvier": 1, "février": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "août": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    }
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.lower())
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = months_fr.get(month_str)
        if month:
            return date(year, month, day)
    # Try ISO format
    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m2:
        return date.fromisoformat(m2.group(1))
    raise ValueError(f"Cannot parse date from: {text!r}")
