from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_BILLING_URL = "https://starlink.com/account/billing"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Seconds to wait after filling a field so the proof-of-work captcha can solve
_CAPTCHA_WAIT = 8


class StarlinkProvider(InvoiceProvider):
    name = "starlink"
    # Saved after first login; reused by fetch_pdf within the same run
    _session_state: dict | None = None

    def is_enabled(self) -> bool:
        return config.STARLINK_ENABLED and bool(config.STARLINK_EMAIL and config.STARLINK_PASS)

    # ── Playwright helpers ─────────────────────────────────────────────────

    def _new_context(self, p, session_state=None):
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=_UA, storage_state=session_state)
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return browser, ctx, page

    def _login(self, page, ctx) -> None:
        from oauth2.gmail_otp import get_starlink_otp

        # 1. Navigate to billing → triggers OIDC redirect to login with proper params
        page.goto(_BILLING_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("input[type='email']", timeout=15000)

        # Dismiss cookie consent banner (Reject All avoids navigation side-effects)
        try:
            page.click("button:has-text('Reject All')", timeout=3000)
            page.wait_for_timeout(500)
        except Exception:
            pass

        # 2. Email step — wait for proof-of-work captcha to solve before submitting
        page.fill("input[type='email']", config.STARLINK_EMAIL)
        page.wait_for_timeout(_CAPTCHA_WAIT * 1000)
        page.click("button[type='submit']:has-text('Next')")
        page.wait_for_selector("input[type='password']", timeout=15000)

        # 3. Password step
        page.fill("input[type='password']", config.STARLINK_PASS)
        page.wait_for_timeout(_CAPTCHA_WAIT * 1000)
        signin_epoch = int(__import__("time").time()) - 10  # small buffer for email delivery
        page.click("button[type='submit']:has-text('Sign In')")

        # 4. OTP step (Two-Step Verification via email)
        try:
            page.wait_for_selector("input[name='oneTimePasscode']", timeout=15000)
            log.info("Starlink: OTP required, fetching from Gmail…")
            otp = get_starlink_otp(after_epoch=signin_epoch, max_wait=90)
            page.fill("input[name='oneTimePasscode']", otp)
            page.click("button[type='submit']:has-text('Verify')")
        except Exception:
            log.debug("Starlink: no OTP step detected")

        # 5. Wait for auth flow to complete (leave the auth/login domain)
        page.wait_for_function(
            "() => !window.location.pathname.startsWith('/auth/')", timeout=30000
        )
        # 6. Navigate explicitly to billing page (post-login redirect may differ)
        page.goto(_BILLING_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        log.info("Starlink: logged in, on billing page")

    # ── Public interface ───────────────────────────────────────────────────

    def list_invoices(self, since: date) -> list[Invoice]:
        from playwright.sync_api import sync_playwright

        invoices = []
        try:
            with sync_playwright() as p:
                browser, ctx, page = self._new_context(p)
                self._login(page, ctx)
                StarlinkProvider._session_state = ctx.storage_state()
                invoices = self._scrape_invoices(page, since)
                browser.close()
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(self.name, f"Scraping failed: {e}")

        log.info("Starlink: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser, ctx, page = self._new_context(
                    p, session_state=StarlinkProvider._session_state
                )
                page.goto(_BILLING_URL, wait_until="domcontentloaded", timeout=30000)

                # Re-login if session expired
                if "auth/login" in page.url:
                    log.info("Starlink: session expired, re-logging in")
                    self._login(page, ctx)
                    StarlinkProvider._session_state = ctx.storage_state()

                page.wait_for_timeout(2000)
                dest = dest_dir / f"starlink_{invoice.invoice_id}_{invoice.issue_date}.pdf"
                self._download_pdf(page, invoice, dest)
                browser.close()

            invoice.pdf_path = dest
            return dest
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(self.name, f"Download failed for {invoice.invoice_id}: {e}")

    # ── Billing page scraping ──────────────────────────────────────────────

    def _scrape_invoices(self, page, since: date) -> list[Invoice]:
        invoices = []
        rows = page.query_selector_all("[class*='row']")
        log.debug("Starlink: found %d candidate rows", len(rows))
        for row in rows:
            text = row.inner_text()
            inv_id = _extract_id(text)
            if not inv_id:
                continue  # skip header and non-invoice rows
            try:
                bill_date = _parse_date(text)
            except ValueError:
                continue
            if bill_date < since:
                continue
            invoices.append(Invoice(
                provider=self.name,
                invoice_id=inv_id,
                issue_date=bill_date,
                amount=_extract_amount(text),
                currency="EUR",
                pdf_url=None,
                pdf_path=None,
                raw={"text": text[:200]},
            ))
        return invoices

    def _download_pdf(self, page, invoice: Invoice, dest: Path) -> None:
        # Find the row containing this invoice ID and click its download button
        row = page.query_selector(f"[class*='row']:has-text('{invoice.invoice_id}')")
        if not row:
            raise RuntimeError(f"Row not found for invoice {invoice.invoice_id}")
        btn = row.query_selector("a, button, [role='button']")
        if not btn:
            raise RuntimeError(f"Download button not found in row for {invoice.invoice_id}")
        with page.expect_download(timeout=30000) as dl_info:
            btn.click()
        dl_info.value.save_as(dest)


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_date(text: str) -> date:
    # ISO format: 2026-04-10
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return date.fromisoformat(m.group(1))
    # US format: 4/10/2026
    m2 = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m2:
        return date(int(m2.group(3)), int(m2.group(1)), int(m2.group(2)))
    # Long format: April 10, 2026
    m3 = re.search(r"(\w+ \d{1,2},?\s*\d{4})", text)
    if m3:
        from datetime import datetime
        return datetime.strptime(m3.group(1).replace(",", ""), "%B %d %Y").date()
    raise ValueError(f"Cannot parse date from: {text!r}")


def _extract_id(text: str) -> str | None:
    # Starlink invoice IDs: INV-DF-FRA-3982858-42483-12
    m = re.search(r"(INV[-\w]+)", text, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_amount(text: str) -> float:
    m = re.search(r"[\$€]\s*([\d.,]+)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return 0.0
