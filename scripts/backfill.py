#!/usr/bin/env python3
"""
Download a provider's invoice history to disk and mark it as handled, WITHOUT
sending anything. Use when a backlog must be forwarded to the accountant by hand
(e.g. invoices older than LOOKBACK_DAYS, or a past accounting period).

PDFs land in the usual DATA_DIR/pdfs/<YYYY-MM>/ layout. Marking them as sent
stops the next monthly collection from mailing them a second time.

Usage:
  python scripts/backfill.py youprice pokawa_mail --days 400
  python scripts/backfill.py youprice --days 400 --dry-run
"""
import argparse
import csv
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import storage
from providers import get_enabled_providers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

MARK = "manuel (backfill — non envoyé par factures2tiime)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("providers", nargs="+", help="Provider names to backfill")
    parser.add_argument("--days", type=int, default=400, help="Look-back window")
    parser.add_argument(
        "--dry-run", action="store_true", help="List only; write nothing"
    )
    parser.add_argument(
        "--manifest",
        metavar="CSV",
        help="Also write a CSV index (date, provider, label, amount, file) — "
             "makes a manual import into the accounting tool tractable",
    )
    args = parser.parse_args()

    storage.init_db()
    since = date.today() - timedelta(days=args.days)
    available = {p.name: p for p in get_enabled_providers()}

    unknown = [n for n in args.providers if n not in available]
    if unknown:
        print(f"Unknown or disabled provider(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(sorted(available))}")
        sys.exit(1)

    written: list[tuple[str, Path, float]] = []
    rows: list[dict] = []
    for name in args.providers:
        provider = available[name]
        invoices = provider.list_invoices(since=since)
        todo = [i for i in invoices if not storage.already_sent(i.provider, i.invoice_id)]
        log.info(
            "%s: %d invoice(s), %d to backfill (%d already handled)",
            name, len(invoices), len(todo), len(invoices) - len(todo),
        )

        for inv in todo:
            dest_dir = config.PDF_DIR / inv.issue_date.strftime("%Y-%m")
            if args.dry_run:
                log.info("  [dry-run] %s %s", inv.issue_date, inv.invoice_id)
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                path = provider.fetch_pdf(inv, dest_dir)
            except Exception as e:
                log.error("  FAILED %s: %s", inv.invoice_id, e)
                continue
            storage.record_invoice(inv)
            storage.update_pdf_path(inv)
            storage.mark_sent(inv, MARK)
            written.append((name, path, inv.amount))
            rows.append({
                "date": inv.issue_date.isoformat(),
                "provider": name,
                # Merchant for Qonto receipts, mail subject elsewhere — whatever
                # identifies the document at a glance during a manual import.
                "libelle": (
                    inv.raw.get("merchant")
                    or inv.raw.get("subject")
                    or inv.raw.get("name")
                    or ""
                ),
                "montant": f"{inv.amount:.2f}",
                "devise": inv.currency,
                "fichier": str(path),
                "reference": inv.invoice_id,
            })

    if args.dry_run:
        print("\nDry run — nothing written.")
        return

    if args.manifest and rows:
        manifest = Path(args.manifest).expanduser()
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: r["date"]))
        print(f"\nIndex CSV : {manifest} ({len(rows)} ligne(s))")

    print(f"\n{len(written)} PDF(s) written under {config.PDF_DIR}\n")
    for name in args.providers:
        rows = [(p, a) for n, p, a in written if n == name]
        if not rows:
            continue
        print(f"── {name} — {len(rows)} fichier(s), {sum(a for _, a in rows):.2f} EUR")
        for path, amount in sorted(rows):
            print(f"   {amount:>7.2f} EUR  {path}")
        print()
    print("Marked as handled in the database — the monthly collection will skip them.")


if __name__ == "__main__":
    main()
