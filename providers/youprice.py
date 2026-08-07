"""
YouPrice (France Numérique) — no public API, but the customer portal is an
Angular SPA backed by a private REST API. Playwright is only used to get through
the login and its emailed one-time code; the invoice list and the PDFs then come
from the API with the bearer token the SPA stores in localStorage.

Login flow: email + password → `.auth-code-modal` asking for a 6-character code
emailed by noreply@youprice.fr → token in localStorage under `user_token`.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path

import requests

import config
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)

_BASE_URL = "https://espace-client.youprice.fr"
_LOGIN_URL = f"{_BASE_URL}/connexion-espace-client"
_API = "https://api.youprice.fr/Vitrine/invoice"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# The SPA login fields carry neither name nor id, so they are matched on their
# placeholder — a generic input[type=text] would hit the site search box.
_EMAIL_INPUT = "input[placeholder='Adresse mail']"
_PASSWORD_INPUT = "input[type='password']"
_SUBMIT = "button.login-submit"

# The 2FA step is a modal overlaying the login form; its buttons carry no type
# attribute, and an unscoped selector resolves to the login button behind it.
_OTP_MODAL = ".auth-code-modal"
_OTP_INPUT = f"{_OTP_MODAL} input[name='codeConfirmation']"
_OTP_SUBMIT = f"{_OTP_MODAL} button.auth-code-submit"


class YoupriceProvider(InvoiceProvider):
    name = "youprice"
    # Bearer token from the SPA, reused by fetch_pdf within the same run
    _token: str | None = None

    def is_enabled(self) -> bool:
        return config.YOUPRICE_ENABLED and bool(
            config.YOUPRICE_USER and config.YOUPRICE_PASS
        )

    # ── Authentication ─────────────────────────────────────────────────────

    def _get_token(self, force: bool = False) -> str:
        if YoupriceProvider._token and not force:
            return YoupriceProvider._token
        YoupriceProvider._token = self._login_and_extract_token()
        return YoupriceProvider._token

    def _login_and_extract_token(self) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            try:
                page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                self._dismiss_cookies(page)

                try:
                    page.wait_for_selector(_EMAIL_INPUT, timeout=20000)
                except Exception:
                    self._dump_debug(page, "no-login-form")
                    raise

                page.fill(_EMAIL_INPUT, config.YOUPRICE_USER)
                page.fill(_PASSWORD_INPUT, config.YOUPRICE_PASS)

                # Buffer for the delivery delay between submit and the code landing
                submit_epoch = int(time.time()) - 10
                page.click(_SUBMIT)
                self._pass_otp(page, submit_epoch)

                page.wait_for_load_state("networkidle", timeout=30000)
                raw = page.evaluate("() => window.localStorage.getItem('user_token')")
                if not raw:
                    self._dump_debug(page, "no-token")
                    raise RuntimeError("Logged in but no user_token in localStorage")
                log.info("YouPrice: logged in, token acquired")
                return _decode_stored_token(raw)
            finally:
                browser.close()

    def _pass_otp(self, page, submit_epoch: int) -> None:
        from oauth2.gmail_otp import get_youprice_otp

        try:
            page.wait_for_selector(_OTP_INPUT, timeout=20000)
        except Exception:
            log.info("YouPrice: no OTP step detected")
            return

        log.info("YouPrice: OTP required, fetching from Gmail…")
        page.fill(_OTP_INPUT, get_youprice_otp(after_epoch=submit_epoch, max_wait=120))
        page.click(_OTP_SUBMIT)
        try:
            page.wait_for_selector(_OTP_MODAL, state="detached", timeout=30000)
        except Exception:
            self._dump_debug(page, "otp-rejected")
            raise RuntimeError("OTP was submitted but the 2FA modal stayed open")

    def _dismiss_cookies(self, page) -> None:
        # Axeptio banner — "Non merci" declines without extra navigation
        for label in ("Non merci", "Tout refuser", "Refuser", "Continuer sans accepter"):
            try:
                page.click(f"button:has-text('{label}')", timeout=3000)
                page.wait_for_timeout(500)
                log.debug("YouPrice: cookie banner dismissed via %r", label)
                return
            except Exception:
                continue

    def _dump_debug(self, page, tag: str) -> None:
        try:
            debug_dir = config.DATA_DIR / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            page.screenshot(path=str(debug_dir / f"youprice_{tag}_{stamp}.png"))
            (debug_dir / f"youprice_{tag}_{stamp}.html").write_text(
                page.content(), encoding="utf-8"
            )
            log.warning("YouPrice: page dumped to %s", debug_dir)
        except Exception as e:
            log.debug("YouPrice: cannot dump debug page: %s", e)

    # ── API calls ──────────────────────────────────────────────────────────

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": _UA,
            "Origin": _BASE_URL,
            "Referer": f"{_BASE_URL}/",
        }

    def _get_json(self, endpoint: str) -> list[dict]:
        """GET an invoice list, re-authenticating once if the token expired."""
        for attempt in (1, 2):
            token = self._get_token(force=attempt == 2)
            resp = requests.get(
                f"{_API}/{endpoint}", headers=self._headers(token), timeout=30
            )
            if resp.status_code in (400, 401, 403) and attempt == 1:
                log.info("YouPrice: token rejected on %s, re-logging in", endpoint)
                continue
            resp.raise_for_status()
            return resp.json() or []
        return []

    # ── Public interface ───────────────────────────────────────────────────

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            # Monthly subscription invoices, plus one-off charges (SIM, options…)
            raw = self._get_json("getMonthlyInvoices") + self._get_json("getDiversInvoices")
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(self.name, f"API call failed: {e}") from e

        invoices = []
        for item in raw:
            try:
                issue_date = _parse_api_date(item.get("invoiceDate"))
                if issue_date is None or issue_date < since:
                    continue
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=str(item["id"]),
                    issue_date=issue_date,
                    amount=float(item.get("montantTTC") or 0.0),
                    currency="EUR",
                    pdf_url=f"{_API}/getFileOfInvoices?id={item['id']}",
                    pdf_path=None,
                    raw={
                        "name": item.get("invoiceName"),
                        "status": item.get("invoiceStatus"),
                    },
                ))
            except Exception as e:
                log.warning("YouPrice: skipping malformed invoice %r: %s", item, e)

        log.info("YouPrice: %d invoice(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        dest = dest_dir / f"youprice_{invoice.issue_date}_{invoice.invoice_id}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        # The PDF endpoint is a POST, and answers with an octet-stream
        url = f"{_API}/getFileOfInvoices?id={invoice.invoice_id}"

        try:
            for attempt in (1, 2):
                token = self._get_token(force=attempt == 2)
                headers = self._headers(token) | {
                    "Accept": "application/svg",
                    "Content-Type": "application/json",
                }
                resp = requests.post(url, headers=headers, timeout=60)
                if resp.status_code in (400, 401, 403) and attempt == 1:
                    log.info("YouPrice: token rejected on download, re-logging in")
                    continue
                resp.raise_for_status()
                break

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


def _decode_stored_token(raw: str) -> str:
    """The SPA JSON-encodes the token, so localStorage holds it *with* quotes —
    sending those verbatim yields a 400 from the API."""
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw.strip('"')
    return raw


def _parse_api_date(raw: str | None) -> date | None:
    """Parse the API's "2026-06-30T00:00:00" invoice date."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        log.warning("YouPrice: unparseable invoiceDate %r", raw)
        return None
