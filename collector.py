import logging
from datetime import date, timedelta

import config
import mailer
import storage
from providers import get_enabled_providers
from providers.base import ProviderError

log = logging.getLogger(__name__)


def run_collection() -> None:
    run_id = storage.start_run()
    since = date.today() - timedelta(days=config.LOOKBACK_DAYS)

    providers_ok: list[str] = []
    providers_err: list[str] = []
    total_new = 0
    total_sent = 0

    log.info("Collection started — since %s", since)

    for provider in get_enabled_providers():
        log.info("Processing provider: %s", provider.name)
        try:
            invoices = provider.list_invoices(since=since)
            for inv in invoices:
                if storage.already_sent(inv.provider, inv.invoice_id):
                    continue

                storage.record_invoice(inv)

                dest = config.PDF_DIR / inv.issue_date.strftime("%Y-%m")
                dest.mkdir(parents=True, exist_ok=True)

                provider.fetch_pdf(inv, dest)
                storage.update_pdf_path(inv)

                mailer.send_invoice(inv)
                storage.mark_sent(inv, config.TIIME_EMAIL)

                total_new += 1
                total_sent += 1
                log.info("Sent: %s/%s", inv.provider, inv.invoice_id)

            providers_ok.append(provider.name)

        except ProviderError as e:
            log.error("Provider error: %s", e)
            providers_err.append(provider.name)
        except Exception as e:
            log.exception("Unexpected error for %s: %s", provider.name, e)
            providers_err.append(provider.name)

    # Retry any invoices downloaded but not yet sent (e.g. crash on previous run)
    for row in storage.get_unsent():
        try:
            from providers.base import Invoice
            from pathlib import Path
            inv = Invoice(
                provider=row["provider"],
                invoice_id=row["invoice_id"],
                issue_date=date.fromisoformat(row["issue_date"]),
                amount=row["amount"] or 0.0,
                currency=row["currency"] or "EUR",
                pdf_url=None,
                pdf_path=Path(row["pdf_path"]),
            )
            mailer.send_invoice(inv)
            storage.mark_sent(inv, config.TIIME_EMAIL)
            total_sent += 1
            log.info("Retry sent: %s/%s", inv.provider, inv.invoice_id)
        except Exception as e:
            log.error("Retry failed for %s/%s: %s", row["provider"], row["invoice_id"], e)

    status = "success" if not providers_err else ("partial" if providers_ok else "error")
    storage.finish_run(run_id, status, providers_ok, providers_err, total_new, total_sent)
    log.info("Collection done — %d sent, %d provider errors", total_sent, len(providers_err))
