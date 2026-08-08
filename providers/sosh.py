"""
Sosh (Orange) — the monthly email only announces that an invoice exists; the
document lives in the Orange customer area, behind a two-step login.

Playwright is used solely to get through that login and the post-login upsell;
the invoice list and the PDFs then come from the private REST API the SPA calls,
reusing the session cookies. Orange defends this login more aggressively than the
other scraped portals, so each step dumps the page to DATA_DIR/debug on failure.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_HOME_URL = "https://espace-client.orange.fr/"
_BILL_PAGE = "https://espace-client.orange.fr/facture-paiement"
_API = "https://espace-client.orange.fr/ecd_wp"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CONSENT = "#didomi-notice-disagree-button"
_LOGIN_INPUT = "input#login"
# Depending on the network the request comes from, Orange may replace the
# identifier form with a chooser listing the accounts it recognises
_ACCOUNT_CHOICE = "[data-testid='choose-account-{login}']"
_OTHER_ACCOUNT = "[data-testid='input-other-account']"
_PASSWORD_INPUT = "input[type='password']"
_SUBMIT = "button[type='submit']"
# Orange emails a 6-digit code when it does not recognise the browser
_OTP_INPUT = "input[autocomplete='one-time-code'], input[name*='code' i]"
_OTP_SENDER = "noreply@orange.fr"


class SoshProvider(InvoiceProvider):
    name = "sosh"
    # Cookies harvested from the Playwright login, reused by the REST calls
    _cookies: dict | None = None

    def is_enabled(self) -> bool:
        return config.SOSH_ENABLED and bool(config.SOSH_USER and config.SOSH_PASS)

    # ── Browser plumbing ───────────────────────────────────────────────────

    def _new_context(self, p, session_state=None):
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=_UA, locale="fr-FR", accept_downloads=True,
            storage_state=session_state,
        )
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return browser, ctx, page

    def _dismiss_consent(self, page) -> None:
        try:
            page.click(_CONSENT, timeout=6000)
            page.wait_for_timeout(600)
            log.debug("Sosh: consent banner declined")
        except Exception:
            log.debug("Sosh: no consent banner")

    def _decline_interstitials(self, page) -> None:
        """Dismiss the post-login upsell screens.

        Orange interposes an "Activez l'authentification renforcée" page between
        the password and the account. Only the decline control is ever clicked:
        accepting would move the account to MySosh app-based sign-in and remove
        password login altogether, permanently locking this provider out.
        """
        for _ in range(3):
            for label in ("Plus tard", "Pas maintenant", "Ignorer", "Continuer sans"):
                try:
                    page.click(f"text={label}", timeout=4000)
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2500)
                    log.info("Sosh: interstitial declined via %r", label)
                    break
                except Exception:
                    continue
            else:
                return

    def _login(self, page) -> None:
        # OTP filter anchor: accept any code arriving after this attempt began.
        # Gmail can index the email under the *sender's* Date header, whose
        # clock may lag — anchoring at click time rejected codes at the boundary.
        attempt_epoch = int(time.time()) - 30
        page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        if "login.orange.fr" not in page.url:
            log.info("Sosh: already authenticated")
            return

        self._dismiss_consent(page)
        self._submit_identifier(page)

        # Step two is rendered only once the identifier is accepted
        try:
            page.wait_for_selector(_PASSWORD_INPUT, timeout=20000)
        except Exception:
            self._dump_debug(page, "no-password-step")
            raise RuntimeError(
                "Orange did not ask for a password — identifier refused, "
                "or a captcha is in the way (see the dump)"
            )
        page.fill(_PASSWORD_INPUT, config.SOSH_PASS)
        page.click(_SUBMIT)
        page.wait_for_timeout(4000)

        self._pass_otp(page, attempt_epoch)
        self._decline_interstitials(page)

        if "login.orange.fr" in page.url:
            self._dump_debug(page, "still-on-login")
            raise RuntimeError("Still on the login page after submitting credentials")
        log.info("Sosh: logged in")

    def _submit_identifier(self, page) -> None:
        """First step: hand the account identifier to Orange.

        Two possible screens: the plain identifier form, or an account chooser
        ("Choisissez l'identifiant pour accéder à votre compte") when Orange
        recognises returning accounts. Whichever shows up first wins.
        """
        choice = _ACCOUNT_CHOICE.format(login=config.SOSH_USER)
        try:
            page.wait_for_selector(
                f"{choice}, {_OTHER_ACCOUNT}, {_LOGIN_INPUT}", timeout=20000
            )
        except Exception:
            self._dump_debug(page, "no-login-form")
            raise

        if page.query_selector(choice):
            log.info("Sosh: account chooser shown, picking %s", config.SOSH_USER)
            page.click(choice)
            return
        if page.query_selector(_OTHER_ACCOUNT):
            # Chooser shown, but the wanted account is not in its list
            log.info("Sosh: account chooser without %s, entering it manually",
                     config.SOSH_USER)
            page.click(_OTHER_ACCOUNT)
            page.wait_for_selector(_LOGIN_INPUT, timeout=20000)
        page.fill(_LOGIN_INPUT, config.SOSH_USER)
        page.click(_SUBMIT)

    def _pass_otp(self, page, attempt_epoch: int) -> None:
        """Orange emails a code when the browser is unknown — read it from Gmail."""
        if not page.query_selector(_OTP_INPUT):
            return
        from oauth2.gmail_otp import DIGITS_6, get_otp

        log.info("Sosh: verification code required, fetching from Gmail…")
        page.fill(_OTP_INPUT, get_otp(
            _OTP_SENDER, pattern=DIGITS_6, label="Orange OTP",
            after_epoch=attempt_epoch, max_wait=120,
        ))
        page.click(_SUBMIT)
        page.wait_for_timeout(4000)

    def _dump_debug(self, page, tag: str) -> None:
        try:
            debug_dir = config.DATA_DIR / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            page.screenshot(path=str(debug_dir / f"sosh_{tag}_{stamp}.png"), full_page=True)
            (debug_dir / f"sosh_{tag}_{stamp}.html").write_text(
                page.content(), encoding="utf-8"
            )
            log.warning("Sosh: page dumped to %s (%s)", debug_dir, tag)
        except Exception as e:
            log.debug("Sosh: cannot dump debug page: %s", e)

    # ── Session & REST ─────────────────────────────────────────────────────

    def _get_cookies(self, force: bool = False) -> dict:
        if SoshProvider._cookies and not force:
            return SoshProvider._cookies
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, ctx, page = self._new_context(p)
            try:
                self._login(page)
                # Land on the billing page so its cookies are issued too
                page.goto(_BILL_PAGE, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                SoshProvider._cookies = {
                    c["name"]: c["value"] for c in ctx.cookies()
                }
            finally:
                browser.close()
        return SoshProvider._cookies

    def _headers(self, accept: str = "application/json") -> dict:
        # The SPA stamps these on every call; without them the API answers 400
        return {
            "accept": accept,
            "cache-control": "no-cache, no-store",
            "content-type": "application/json",
            "user-agent": _UA,
            "x-app-device-type": "desktop",
            "x-orange-caller-id": "ECQ",
            "x-orange-origin-id": "ECQ",
            "x-orange-request-id": str(uuid.uuid4()),
            "x-orange-session-id": str(uuid.uuid4()),
        }

    def _api_get(self, path: str, accept: str = "application/json", force: bool = False):
        cookies = self._get_cookies(force=force)
        resp = requests.get(
            f"{_API}/{path}", headers=self._headers(accept), cookies=cookies, timeout=60
        )
        if resp.status_code in (401, 403) and not force:
            log.info("Sosh: session rejected, logging in again")
            return self._api_get(path, accept, force=True)
        resp.raise_for_status()
        return resp

    def _contract_ids(self) -> list[str]:
        data = self._api_get(
            "portfoliomanager/portfolio?filter=telco,security&includeContracts=true",
            accept="application/json;version=1",
        ).json()
        cids = [c["cid"] for c in data.get("contracts", []) if c.get("cid")]
        if not cids:
            raise RuntimeError("No contract returned by the portfolio API")
        log.debug("Sosh: contracts %s", cids)
        return cids

    # ── Public interface ───────────────────────────────────────────────────

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            invoices: list[Invoice] = []
            for cid in self._contract_ids():
                data = self._api_get(
                    f"facture/v2.0/billsAndPaymentInfos/users/current/contracts/{cid}"
                    "?detail=true"
                ).json()
                for bill in _bill_list(data):
                    issue_date = _parse_date(bill.get("date"))
                    if issue_date is None or issue_date < since:
                        continue
                    invoices.append(Invoice(
                        provider=self.name,
                        invoice_id=f"{cid}_{issue_date.isoformat()}",
                        issue_date=issue_date,
                        # The API reports cents
                        amount=round((bill.get("amount") or 0) / 100, 2),
                        currency="EUR",
                        pdf_url=None,
                        pdf_path=None,
                        raw={
                            "cid": cid,
                            "href_pdf": bill.get("hrefPdf"),
                            "bill_number": bill.get("id"),
                        },
                    ))
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(self.name, f"Listing failed: {e}") from e

        log.info("Sosh: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        href = invoice.raw.get("href_pdf")
        if not href:
            raise ProviderError(
                self.name, f"No PDF reference for {invoice.invoice_id}"
            )
        dest = dest_dir / f"sosh_{invoice.issue_date}_{invoice.raw.get('cid','')}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = self._api_get(f"facture/v1.0/pdf{href}", accept="application/pdf")
            if not resp.content.startswith(b"%PDF"):
                raise RuntimeError(
                    f"Expected a PDF, got {resp.headers.get('content-type')} "
                    f"({len(resp.content)} bytes)"
                )
            dest.write_bytes(resp.content)
            invoice.pdf_path = dest
            return dest
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                self.name, f"Download failed for {invoice.invoice_id}: {e}"
            ) from e


# ── Helpers ────────────────────────────────────────────────────────────────


def _bill_list(payload: dict) -> list[dict]:
    """Every bill of a contract: the history, plus the latest if it is missing."""
    history = (payload.get("billsHistory") or {}).get("billList") or []
    bills = list(history)
    last = payload.get("lastBill")
    if last and last.get("date") not in {b.get("date") for b in bills}:
        bills.append(last)
    return bills


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        log.warning("Sosh: unparseable bill date %r", raw)
        return None
