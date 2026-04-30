# factures2tiime

> **Automated invoice collection & delivery pipeline — built end-to-end with Claude AI**

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-arm64-2496ED?logo=docker)](https://www.docker.com/)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite)](https://www.sqlite.org/)
[![Built with Claude](https://img.shields.io/badge/Built%20with-Claude%20AI-8A2BE2)](https://claude.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## What it does

Every month, invoices pile up across a dozen SaaS and cloud providers. Downloading them one by one, then forwarding them to your accountant, is tedious, error-prone, and frankly a waste of time.

**factures2tiime** solves this completely:

1. On the 3rd of each month at 6 AM, a Docker container wakes up
2. It hits **15+ provider APIs** — REST, OAuth2, Playwright scraping, Gmail parsing
3. It downloads every new invoice as a PDF
4. It sends each one as an email attachment directly to the [Tiime](https://www.tiime.fr/) accounting inbox
5. It goes back to sleep until next month

Zero manual steps. Zero missed invoices. Full audit trail in SQLite.

---

## Built entirely with Claude AI

This project is a concrete example of **AI-assisted software engineering at its most productive**.

The entire system — architecture design, provider integrations, OAuth2 flows, crash-safe storage patterns, Docker configuration, and test suite — was conceived and implemented in a tight feedback loop with **Claude Sonnet** as an AI pair programmer.

What that means in practice:

- **Architecture decisions** were discussed and validated with Claude before writing a single line
- **Complex flows** (Starlink login + Gmail OTP polling, Microsoft Azure async billing, Qonto 90-day refresh tokens) were designed collaboratively, iterating on edge cases in real time
- **Code was generated, reviewed, and refactored** by Claude with full awareness of the codebase context
- **Security patterns** (non-root Docker user, secret isolation via `.env`, no credentials in code) were enforced by Claude throughout
- The project went from idea to **production-running container** faster than any traditional development approach

> This is not "AI wrote some boilerplate." This is using Claude as a **senior engineer** who holds the entire system in mind — and who doesn't get tired.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container (arm64)                  │
│                                                             │
│  APScheduler ──► collector.py                               │
│  (3rd/month)       │                                        │
│                    ├──► OVH API          ┐                  │
│                    ├──► Scaleway API     │                  │
│                    ├──► Microsoft 365 ×2 │  REST + OAuth2   │
│                    ├──► Qonto OAuth2     │                  │
│                    ├──► Infomaniak API   │                  │
│                    ├──► Atlassian 2LO    ┘                  │
│                    │                                        │
│                    ├──► Free Mobile     ┐                   │
│                    ├──► Starlink        │  Playwright       │
│                    │     └── Gmail OTP  │  (headless)       │
│                    │                   ┘                   │
│                    ├──► Starlink Mail   ┐                   │
│                    ├──► Google W.Mail   │  Gmail API        │
│                    ├──► Alan Mail       │  (OAuth2)         │
│                    ├──► Anthropic Mail  │                   │
│                    ├──► Mistral Mail    ┘                   │
│                    │                                        │
│                    ▼                                        │
│               storage.py  ◄──► factures.db (SQLite)        │
│               (idempotent,                                  │
│                crash-safe)                                  │
│                    │                                        │
│                    ▼                                        │
│               mailer.py  ──► Mailjet API                   │
│                                    │                        │
└────────────────────────────────────┼────────────────────────┘
                                     ▼
                         justif+XXXX@tiime.fr
                         (accountant inbox)
```

---

## Provider integrations

| Provider | Method | Auth |
|---|---|---|
| OVH | REST `/me/bill` + PDF URL | App Key / Secret / Consumer Key |
| Scaleway | REST billing API (paginated) | `X-Auth-Token` |
| Microsoft 365 ×2 | Azure Billing REST + async polling | OAuth2 `client_credentials` |
| Qonto | REST `/v2/client_invoices` + attachments | OAuth2 authorization_code + 90d refresh |
| Infomaniak | REST `/1/invoicing/{id}/invoice-pdf` | Bearer token |
| Atlassian | Commerce API `/v1/invoices/{id}/download` | OAuth2 2LO (60min tokens) |
| Free Mobile | Portal scraping | Playwright (opt-in) |
| Starlink | Portal scraping + Gmail OTP | Playwright + Gmail API (opt-in) |
| Starlink (mail) | Gmail search + attachment | Gmail API OAuth2 |
| Google Workspace | Gmail search + attachment | Gmail API OAuth2 |
| Alan | Gmail search + attachment | Gmail API OAuth2 |
| Anthropic | Gmail search + attachment | Gmail API OAuth2 |
| Atlassian (mail) | Gmail search + attachment | Gmail API OAuth2 |
| Mailjet | Gmail search + attachment | Gmail API OAuth2 |
| Mistral | Gmail search + attachment | Gmail API OAuth2 |

---

## Key design decisions

### Idempotent by design

Every invoice is recorded in SQLite with `(provider, invoice_id)` as a unique key **before** the email is sent. If the process crashes mid-run, the next execution picks up exactly where it left off — no duplicates, no gaps.

```
download PDF → INSERT (emailed_at=NULL) → send email → UPDATE emailed_at
                                                ↑
                             retried on next run if NULL
```

### OAuth2 token lifecycle

A generic `oauth2/refresher.py` handles all token refresh scenarios:
- Access tokens refreshed 5 minutes before expiry
- Refresh tokens persisted in SQLite across container restarts
- Each provider's quirks (1h/90d for Qonto, 60min for Atlassian, no refresh for Azure) are encapsulated

### Provider abstraction

All integrations implement a single ABC:

```python
class InvoiceProvider(ABC):
    def list_invoices(self, since: date) -> list[Invoice]: ...
    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path: ...
    def is_enabled(self) -> bool: ...
```

Adding a new provider = implementing 3 methods. The orchestrator doesn't change.

### Crash-resistant Playwright

For providers with no invoice API (Starlink, Free Mobile), Playwright runs headless Chromium. The Starlink flow handles: login → password → captcha wait → OTP polling from Gmail → invoice download. All configurable, all opt-in.

---

## Stack

- **Python 3.11** — runtime
- **Docker / docker-compose** — containerized, `linux/arm64` (Apple Silicon)
- **SQLite** — local persistence (invoices, tokens, run logs)
- **APScheduler** — cron scheduling inside the container
- **Playwright** — headless browser for non-API providers
- **Mailjet** — transactional email delivery
- **Gmail API** — OTP polling + email-based invoice extraction
- **pytest** — unit + integration tests with SQLite fixtures

---

## Getting started

### Prerequisites

- Docker Desktop (Mac with Apple Silicon)
- A [Mailjet](https://www.mailjet.com/) account (free tier is sufficient)
- API credentials for the providers you want to enable (see `.env.example`)

### Setup

```bash
# Clone and configure
git clone https://github.com/yourname/factures2tiime
cd factures2tiime
cp .env.example .env
# Fill in your credentials in .env

# For Qonto (OAuth2 authorization_code — one-time)
docker compose run --rm factures2tiime python scripts/setup_qonto.py

# For Gmail-based providers (one-time)
docker compose run --rm factures2tiime python scripts/setup_gmail.py

# Build and run
docker compose build
docker compose up -d
```

### Manual trigger

```bash
docker compose run --rm factures2tiime python scripts/run_now.py
```

### View logs

```bash
docker compose logs -f factures2tiime
```

### Run tests

```bash
pytest tests/ -v
```

---

## Configuration

All configuration is via environment variables. See [`.env.example`](.env.example) for the full reference.

Key settings:

```env
# Scheduling
COLLECTION_DAY=3        # Day of month to run
COLLECTION_HOUR=6       # Hour (Europe/Paris)
LOOKBACK_DAYS=40        # How far back to look for invoices

# Delivery
MAILJET_API_KEY=...
MAILJET_SECRET_KEY=...
MAIL_FROM=factures@yourdomain.com
TIIME_EMAIL=justif+XXXX@tiime.fr

# Optional providers (require Playwright)
FREE_MOBILE_ENABLED=false
STARLINK_ENABLED=false
```

---

## Project structure

```
factures2tiime/
├── main.py              # Scheduler entry point
├── config.py            # Env loading & validation
├── collector.py         # Orchestrator
├── storage.py           # SQLite schema + helpers
├── mailer.py            # Mailjet wrapper
├── providers/
│   ├── base.py          # InvoiceProvider ABC + Invoice dataclass
│   ├── __init__.py      # Provider factory
│   ├── ovh.py
│   ├── scaleway.py
│   ├── microsoft365.py
│   ├── qonto.py
│   ├── infomaniak.py
│   ├── atlassian.py
│   ├── free_mobile.py   # Playwright
│   ├── starlink.py      # Playwright + Gmail OTP
│   ├── gmail_base.py    # Shared Gmail API utilities
│   ├── *_mail.py        # Email-based providers (×7)
│   └── stubs.py         # Disabled stubs
├── oauth2/
│   ├── token_store.py   # SQLite-backed token persistence
│   ├── refresher.py     # Generic token refresh
│   └── gmail_otp.py     # Gmail polling for OTP codes
├── scripts/
│   ├── run_now.py       # Manual trigger
│   ├── setup_qonto.py   # Qonto OAuth2 init
│   ├── setup_gmail.py   # Gmail OAuth2 init
│   └── reset_state.py   # Clear sent state for a provider/month
├── tests/               # pytest suite
├── data/                # Docker volume (SQLite + PDFs)
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Why this project matters

Most automation scripts break at the first API change, stop working after a token expires, or send duplicate invoices if interrupted. This one doesn't — because the failure modes were thought through from the start, not patched after incidents.

The real value isn't the code itself. It's the **methodology**: using Claude to explore the problem space, challenge assumptions, design for correctness, and ship production-quality software quickly.

This project is proof that a single developer, working with the right AI tools, can build what would typically require a small team.

---

## License

MIT
