"""
Render a receipt into a PDF the accountant can file.

Some vendors (Pokawa, Apple subscriptions, …) never attach a PDF — the receipt
*is* the email body. Others (Qonto transaction attachments) hand over a photo of
a paper receipt. Both are turned into a proper document here, with a header
recalling where it came from, because the mail pipeline only ships PDFs.
"""
from __future__ import annotations

import base64
import html as html_lib
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_HEADER_CSS = """
<style>
  @page { size: A4; margin: 14mm; }
  body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; }
  .f2t-header {
    border-bottom: 2px solid #333; margin-bottom: 18px; padding-bottom: 10px;
    font-size: 11px; color: #333; line-height: 1.5;
  }
  .f2t-header .f2t-subject { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
  .f2t-header .f2t-meta span { color: #666; }
  .f2t-body { white-space: pre-wrap; font-size: 12px; line-height: 1.5; }
</style>
"""


def build_header(
    sender: str,
    subject: str,
    issue_date: date,
    extra: dict[str, str] | None = None,
) -> str:
    header = (
        '<div class="f2t-header">'
        f'<div class="f2t-subject">{html_lib.escape(subject or "(sans objet)")}</div>'
        f'<div class="f2t-meta"><span>De :</span> {html_lib.escape(sender)}'
        f' &nbsp;·&nbsp; <span>Date :</span> {issue_date.isoformat()}</div>'
    )
    if extra:
        pairs = " &nbsp;·&nbsp; ".join(
            f"<span>{html_lib.escape(k)} :</span> {html_lib.escape(v)}"
            for k, v in extra.items()
        )
        header += f'<div class="f2t-meta">{pairs}</div>'
    return header + "</div>"


def wrap_html(body_html: str, sender: str, subject: str, issue_date: date) -> str:
    """Prepend the traceability header to an HTML mail body."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        f"{_HEADER_CSS}</head><body>"
        f"{build_header(sender, subject, issue_date)}{body_html}"
        "</body></html>"
    )


def wrap_text(body_text: str, sender: str, subject: str, issue_date: date) -> str:
    """Same, for a plain-text mail body."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        f"{_HEADER_CSS}</head><body>"
        f"{build_header(sender, subject, issue_date)}"
        f'<div class="f2t-body">{html_lib.escape(body_text)}</div>'
        "</body></html>"
    )


def render_pdf(document_html: str, dest: Path) -> Path:
    """Render a complete HTML document to a PDF file using headless Chromium."""
    from playwright.sync_api import sync_playwright

    dest.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Remote images (logos, tracking pixels) may never settle — fall back
            # to a plain load so a slow tracker cannot block the whole run.
            try:
                page.set_content(document_html, wait_until="networkidle", timeout=20000)
            except Exception:
                log.debug("mail_pdf: networkidle timed out, rendering as-is")
                page.set_content(document_html, wait_until="load", timeout=10000)
            page.pdf(path=str(dest), format="A4", print_background=True)
        finally:
            browser.close()
    return dest


def image_to_pdf(
    image_bytes: bytes,
    content_type: str,
    dest: Path,
    *,
    source: str,
    subject: str,
    issue_date: date,
    extra: dict[str, str] | None = None,
) -> Path:
    """Wrap a scanned/photographed receipt into a one-page PDF.

    The image is embedded as a data URI — a strict CSP is irrelevant here, but
    the renderer has no access to the original file otherwise.
    """
    mime = content_type or "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode()
    document = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        f"{_HEADER_CSS}"
        "<style>.f2t-scan{max-width:100%;max-height:235mm;"
        "display:block;margin:0 auto;}</style></head><body>"
        f"{build_header(source, subject, issue_date, extra)}"
        f"<img class='f2t-scan' src='data:{mime};base64,{encoded}'/>"
        "</body></html>"
    )
    return render_pdf(document, dest)


def mail_to_pdf(
    dest: Path,
    *,
    sender: str,
    subject: str,
    issue_date: date,
    html_body: str = "",
    text_body: str = "",
) -> Path:
    """Render a mail body (HTML preferred, text fallback) to `dest`."""
    if html_body.strip():
        document = wrap_html(html_body, sender, subject, issue_date)
    elif text_body.strip():
        document = wrap_text(text_body, sender, subject, issue_date)
    else:
        raise ValueError("Mail has neither an HTML nor a text body to render")
    return render_pdf(document, dest)
