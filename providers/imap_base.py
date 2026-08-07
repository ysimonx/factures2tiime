"""
IMAP counterpart of `gmail_base` — for invoice mailboxes that are not Gmail.

Gmail providers can hit the REST API one message at a time; IMAP logins are far
more expensive, so `fetch_messages` opens a single connection and returns fully
parsed messages (bodies included). Providers cache what they need for the run
rather than reconnecting in `fetch_pdf`.
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

import config

log = logging.getLogger(__name__)

_MAX_MESSAGES = 100


@dataclass
class MailMessage:
    message_id: str
    subject: str
    sender: str
    date: date
    html_body: str = ""
    text_body: str = ""
    pdf_attachments: list[dict] = field(default_factory=list)

    @property
    def body_text(self) -> str:
        """Plain text of the message, HTML stripped if that's all there is."""
        return self.text_body or strip_html(self.html_body)


def is_configured() -> bool:
    return bool(config.IMAP_HOST and config.IMAP_USER and config.IMAP_PASSWORD)


@contextmanager
def connect(folder: str | None = None):
    conn = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
    try:
        conn.login(config.IMAP_USER, config.IMAP_PASSWORD)
        typ, _ = conn.select(folder or config.IMAP_FOLDER, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Cannot select folder {folder or config.IMAP_FOLDER!r}")
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass


def fetch_messages(
    sender: str,
    since: date,
    *,
    folder: str | None = None,
    subject: str | None = None,
) -> list[MailMessage]:
    """Return parsed messages from `sender` received on/after `since`.

    IMAP SINCE has day granularity and is server-side inclusive; callers still
    filter on the parsed date because some servers are sloppy about time zones.
    """
    criteria = ["FROM", f'"{sender}"', "SINCE", since.strftime("%d-%b-%Y")]
    if subject:
        criteria += ["SUBJECT", f'"{subject}"']

    with connect(folder) as conn:
        typ, data = conn.uid("SEARCH", None, *criteria)
        if typ != "OK":
            raise RuntimeError(f"IMAP SEARCH failed: {typ}")
        uids = (data[0] or b"").split()
        if len(uids) > _MAX_MESSAGES:
            log.warning(
                "IMAP: %d messages from %s, keeping the %d most recent",
                len(uids), sender, _MAX_MESSAGES,
            )
            uids = uids[-_MAX_MESSAGES:]

        messages: list[MailMessage] = []
        for uid in uids:
            typ, raw = conn.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                log.warning("IMAP: cannot fetch uid %s", uid.decode())
                continue
            try:
                messages.append(parse_message(raw[0][1], fallback_id=uid.decode()))
            except Exception as e:
                log.warning("IMAP: cannot parse uid %s: %s", uid.decode(), e)

    return messages


def parse_message(raw_bytes: bytes, fallback_id: str = "") -> MailMessage:
    msg = email.message_from_bytes(raw_bytes)
    html_body, text_body, pdfs = _walk(msg)
    return MailMessage(
        message_id=_message_id(msg, fallback_id),
        subject=_decode(msg.get("Subject", "")),
        sender=_sender_address(msg),
        date=_msg_date(msg),
        html_body=html_body,
        text_body=text_body,
        pdf_attachments=pdfs,
    )


# ── Parsing helpers ────────────────────────────────────────────────────────


def _walk(msg: Message) -> tuple[str, str, list[dict]]:
    html_body, text_body, pdfs = "", "", []

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = _decode(part.get_filename() or "")
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()

        if ctype == "application/pdf" or filename.lower().endswith(".pdf"):
            payload = part.get_payload(decode=True)
            if payload:
                pdfs.append({"filename": filename or "invoice.pdf", "content": payload})
            continue

        if "attachment" in disposition:
            continue  # non-PDF attachment (logo, ics, …) — not a body

        if ctype == "text/html" and not html_body:
            html_body = _decode_payload(part)
        elif ctype == "text/plain" and not text_body:
            text_body = _decode_payload(part)

    return html_body, text_body, pdfs


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _decode(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _sender_address(msg: Message) -> str:
    raw = _decode(msg.get("From", ""))
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1) if m else raw.strip()


def _message_id(msg: Message, fallback_id: str) -> str:
    mid = (msg.get("Message-ID") or "").strip().strip("<>")
    if not mid:
        return f"uid-{fallback_id}"
    # Message-IDs end up in filenames and in the DB unique key
    return re.sub(r"[^A-Za-z0-9._@-]", "_", mid)


def _msg_date(msg: Message) -> date:
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).date()
        except Exception:
            log.debug("IMAP: unparseable Date header %r", raw)
    return datetime.now(timezone.utc).date()


def strip_html(html: str) -> str:
    """Crude HTML → text, good enough for amount/reference extraction."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as html_lib
    text = html_lib.unescape(text)
    return re.sub(r"[ \t\xa0]+", " ", text).strip()
