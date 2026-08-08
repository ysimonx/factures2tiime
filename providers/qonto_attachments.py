"""
Receipts scanned into Qonto and attached to a card transaction — restaurants,
taxis, one-off purchases: everything with no vendor API and no invoice email.

This is deliberately separate from `qonto`, which lists /v2/client_invoices —
the invoices *you* issue to your clients. Different resource, different scope.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

import config
from providers import mail_pdf, qonto_base
from providers.base import Invoice, InvoiceProvider, ProviderError

log = logging.getLogger(__name__)


class QontoAttachmentsProvider(InvoiceProvider):
    name = "qonto_attachments"

    def is_enabled(self) -> bool:
        return config.QONTO_ATTACHMENTS_ENABLED and qonto_base.is_configured()

    def list_invoices(self, since: date) -> list[Invoice]:
        try:
            transactions = qonto_base.list_transactions_with_attachments(since)
        except Exception as e:
            raise ProviderError(self.name, f"Failed to list transactions: {e}") from e

        invoices: list[Invoice] = []
        skipped: list[str] = []
        # One attachment can be linked to several transactions (a monthly
        # invoice covering multiple fees); it is still a single justificatif.
        seen: set[str] = set()

        for tx in transactions:
            merchant = _merchant(tx)
            if _is_covered_elsewhere(merchant):
                skipped.append(merchant)
                continue

            settled = _settled_date(tx)
            if settled is None or settled < since:
                continue

            # One invoice per attachment: a transaction may carry several
            # (receipt + itemised bill), and each is its own justificatif.
            for att in tx.get("attachments") or []:
                att_id = att.get("id")
                if not att_id or att_id in seen:
                    continue
                seen.add(att_id)
                invoices.append(Invoice(
                    provider=self.name,
                    invoice_id=att_id,
                    issue_date=settled,
                    amount=abs(float(tx.get("amount") or 0)),
                    currency=tx.get("currency") or "EUR",
                    pdf_url=None,  # URLs expire after 30 min — resolved at download
                    pdf_path=None,
                    raw={
                        "transaction_id": tx.get("id"),
                        "merchant": merchant,
                        "file_name": att.get("file_name"),
                    },
                    label=merchant or None,
                    details=_details(tx, merchant),
                ))

        if skipped:
            log.info(
                "QontoAttachments: %d receipt(s) skipped, already collected by a "
                "dedicated provider (%s)",
                len(skipped), ", ".join(sorted(set(skipped))[:8]),
            )
        log.info("QontoAttachments: %d receipt(s) since %s", len(invoices), since)
        return invoices

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        transaction_id = invoice.raw.get("transaction_id")
        if not transaction_id:
            raise ProviderError(
                self.name, f"No transaction for attachment {invoice.invoice_id}"
            )
        try:
            # Re-resolve rather than reuse the listing URL: those expire in 30 min
            # and a large run can easily outlive that.
            attachments = qonto_base.transaction_attachments(transaction_id)
            att = next(
                (a for a in attachments if a.get("id") == invoice.invoice_id), None
            )
            if att is None:
                raise RuntimeError(f"Attachment {invoice.invoice_id} is gone")

            # Qonto's probative copy is the legally certified one — prefer it
            source = att.get("probative_attachment") or {}
            if not source.get("url"):
                source = att

            content = qonto_base.download(source["url"])
            content_type = (source.get("file_content_type") or "").lower()
            merchant = invoice.raw.get("merchant") or "Qonto"
            slug = _slug(merchant)
            # The full id, never a prefix: Qonto ids are UUIDv7, so their leading
            # characters are a timestamp — two attachments filed in the same
            # instant would collide and one would silently overwrite the other.
            dest = dest_dir / f"qonto_{invoice.issue_date}_{slug}_{invoice.invoice_id}.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)

            if content.startswith(b"%PDF"):
                # Never touched: the probative copy is legally certified, and a
                # cover page could also throw off Tiime's OCR. The transaction
                # context travels in the mail subject/body instead.
                dest.write_bytes(content)
            elif content_type.startswith("image/") or _looks_like_image(content):
                # The merchant is already in the header's source line
                extra = {"Montant": f"{invoice.amount:.2f} {invoice.currency}"} \
                    if invoice.amount else {}
                extra.update(
                    (k, v) for k, v in invoice.details.items() if k != "Marchand"
                )
                mail_pdf.image_to_pdf(
                    content,
                    content_type or "image/jpeg",
                    dest,
                    source=f"Qonto — {merchant}",
                    subject=invoice.raw.get("file_name") or "Justificatif",
                    issue_date=invoice.issue_date,
                    extra=extra or None,
                )
            else:
                raise RuntimeError(
                    f"Unsupported attachment type {content_type!r} "
                    f"({len(content)} bytes)"
                )

            invoice.pdf_path = dest
            return dest
        except Exception as e:
            raise ProviderError(
                self.name, f"Download failed for {invoice.invoice_id}: {e}"
            ) from e


# ── Helpers ────────────────────────────────────────────────────────────────

_OPERATION_LABELS = {
    "card": "Carte",
    "transfer": "Virement",
    "direct_debit": "Prélèvement",
    "qonto_fee": "Frais Qonto",
    "cheque": "Chèque",
}


def _merchant(tx: dict) -> str:
    return (tx.get("clean_counterparty_name") or tx.get("label") or "").strip()


def _details(tx: dict, merchant: str) -> dict[str, str]:
    """Transaction context worth forwarding to the accountant.

    Everything here is already in the listing response — no extra API call.
    Keys are the French labels printed verbatim in the mail body.
    """
    details: dict[str, str] = {}
    if merchant:
        details["Marchand"] = merchant
    if tx.get("transaction_id"):
        details["Transaction"] = str(tx["transaction_id"])
    if payment := _payment(tx):
        details["Paiement"] = payment
    if vat := _vat(tx):
        details["TVA"] = vat
    # The raw bank label (e.g. "POKAWA 13480 CABRIES CB") is what appears on
    # the statement — keep it when the cleaned merchant name replaced it.
    raw_label = (tx.get("label") or "").strip()
    if raw_label and raw_label != merchant:
        details["Libellé"] = raw_label
    if note := (tx.get("note") or "").strip():
        details["Note"] = note
    if category := (tx.get("category") or "").strip():
        details["Catégorie"] = category.replace("_", " ")
    # Foreign-currency purchase: the receipt shows an amount the EUR debit
    # won't match — spell out the original one.
    local_currency = tx.get("local_currency")
    if (
        local_currency
        and local_currency != (tx.get("currency") or "EUR")
        and tx.get("local_amount")
    ):
        details["Montant local"] = (
            f"{abs(float(tx['local_amount'])):.2f} {local_currency}"
        )
    return details


def _payment(tx: dict) -> str | None:
    operation = tx.get("operation_type")
    if not operation:
        return None
    label = _OPERATION_LABELS.get(operation, operation)
    if operation == "card" and (digits := tx.get("card_last_digits")):
        label += f" ****{digits}"
    return label


def _vat(tx: dict) -> str | None:
    amount = tx.get("vat_amount")
    if not amount:
        return None
    text = f"{abs(float(amount)):.2f} {tx.get('currency') or 'EUR'}"
    rate = tx.get("vat_rate")
    # Qonto uses -1 for "multiple rates" — the amount alone is still right
    if rate and float(rate) > 0:
        text += f" ({float(rate):g} %)"
    return text


def _is_covered_elsewhere(merchant: str) -> bool:
    low = merchant.lower()
    return any(skip in low for skip in config.QONTO_ATTACHMENTS_SKIP)


def _settled_date(tx: dict) -> date | None:
    raw = tx.get("settled_at") or tx.get("emitted_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(
            str(raw).replace("Z", "+00:00")
        ).astimezone(timezone.utc).date()
    except ValueError:
        log.warning("QontoAttachments: unparseable settled_at %r", raw)
        return None


def _slug(merchant: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", merchant).strip("-").lower()
    return (cleaned or "transaction")[:30]


def _looks_like_image(content: bytes) -> bool:
    return content[:3] == b"\xff\xd8\xff" or content[:8] == b"\x89PNG\r\n\x1a\n"
