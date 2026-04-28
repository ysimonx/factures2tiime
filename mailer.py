import base64
import logging
from pathlib import Path

from mailjet_rest import Client

import config
from providers.base import Invoice

log = logging.getLogger(__name__)


def _client() -> Client:
    return Client(
        auth=(config.MAILJET_API_KEY, config.MAILJET_SECRET_KEY),
        version="v3.1",
    )


def send_invoice(inv: Invoice) -> None:
    if not inv.pdf_path or not Path(inv.pdf_path).exists():
        raise ValueError(f"PDF not found for {inv.provider}/{inv.invoice_id}")

    pdf_bytes = Path(inv.pdf_path).read_bytes()
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    filename = Path(inv.pdf_path).name

    subject = (
        f"[{inv.provider.upper()}] Facture {inv.issue_date.strftime('%Y-%m')}"
        f" — {inv.amount:.2f} {inv.currency}"
    )
    body = (
        f"Fournisseur : {inv.provider}\n"
        f"Référence   : {inv.invoice_id}\n"
        f"Date        : {inv.issue_date}\n"
        f"Montant     : {inv.amount:.2f} {inv.currency}\n"
    )

    data = {
        "Messages": [
            {
                "From": {"Email": config.MAIL_FROM, "Name": "factures2tiime"},
                "To": [{"Email": config.TIIME_EMAIL}],
                "Cc": [{"Email": cc}] if (cc := config.MAIL_CC) else [],
                "Subject": subject,
                "TextPart": body,
                "Attachments": [
                    {
                        "ContentType": "application/pdf",
                        "Filename": filename,
                        "Base64Content": pdf_b64,
                    }
                ],
            }
        ]
    }

    result = _client().send.create(data=data)
    if result.status_code not in (200, 201):
        raise RuntimeError(
            f"Mailjet error {result.status_code}: {result.json()}"
        )
    log.info("Sent %s/%s to %s", inv.provider, inv.invoice_id, config.TIIME_EMAIL)
