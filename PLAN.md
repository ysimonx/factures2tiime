# Plan : factures2tiime

## Contexte

L'utilisateur collecte manuellement des factures auprès d'une dizaine de fournisseurs cloud/SaaS (OVH, Scaleway, Microsoft 365 ×2, Qonto, Infomaniak, Atlassian, Google, Apple, Anthropic, Free Mobile, Starlink, Alan, Mailjet, YouTube) et doit les transmettre mensuellement à son comptable via l'adresse de dépôt Tiime `justif+kysoe@tiime.fr`. L'objectif est d'automatiser cette collecte + envoi dans un conteneur Docker qui tourne sur Mac.

---

## Bilan des APIs disponibles

| Fournisseur | Méthode | Auth |
|---|---|---|
| OVH | ✅ REST `/me/bill` + `pdfUrl` | App Key / Secret / Consumer Key |
| Scaleway | ✅ REST `/billing/v2beta1/invoices/{id}/download` | `X-Auth-Token` |
| Microsoft 365 ×2 | ✅ Azure Billing REST API | OAuth2 client_credentials (1 app par tenant) |
| Qonto | ✅ REST `/v2/client_invoices` + attachments | OAuth2 authorization_code + refresh token |
| Infomaniak | ✅ REST `/1/invoicing/{id}/invoice-pdf` | Bearer token (depuis dashboard) |
| Atlassian | ✅ Commerce API `/v1/invoices/{id}/download` | OAuth2 2LO (service account) |
| Google Workspace | ❌ Aucune API invoice | Stub — email fallback manuel |
| Apple iCloud | ❌ Aucune API | Stub — email fallback manuel |
| Anthropic | ❌ Aucune API billing | Stub — email Stripe |
| Free Mobile | ❌ Aucune API | Playwright scraping (opt-in) |
| Starlink | ❌ Enterprise only | Playwright scraping (opt-in) |
| Alan | ❌ Aucune API publique | Stub — manuel |
| Mailjet | ❌ Aucune API billing | Stub — manuel |
| YouTube Premium | ❌ Aucune API | Stub — email fallback |

**Envoi vers Tiime** : Mailjet API (`POST /v3.1/send`), un email par facture avec PDF en pièce jointe.

---

## Architecture

```
factures2tiime/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── requirements.txt
│
├── main.py            # APScheduler — cron le 3 du mois à 6h (Europe/Paris)
├── config.py          # Chargement env vars, validation
├── storage.py         # SQLite : schema, db_cursor(), init_db()
├── collector.py       # Orchestrateur : itère les providers, appelle mailer
├── mailer.py          # Mailjet API — un email par facture
│
├── providers/
│   ├── base.py        # ABC InvoiceProvider + dataclass Invoice + ProviderError
│   ├── ovh.py
│   ├── scaleway.py
│   ├── microsoft365.py  # 2 tenants Azure AD fusionnés
│   ├── qonto.py
│   ├── infomaniak.py
│   ├── atlassian.py
│   ├── free_mobile.py   # Playwright (opt-in FREE_MOBILE_ENABLED)
│   ├── starlink.py      # Playwright (opt-in STARLINK_ENABLED)
│   └── stubs.py         # Google, Apple, Anthropic, Alan, Mailjet, YouTube
│
├── oauth2/
│   ├── token_store.py   # Lecture/écriture table oauth2_tokens dans SQLite
│   └── refresher.py     # Refresh générique (Qonto 1h access / 90j refresh)
│
├── scripts/
│   ├── run_now.py        # Déclenchement manuel immédiat
│   ├── setup_qonto.py    # Authorization_code flow Qonto (une seule fois)
│   └── reset_state.py    # Efface sent_invoices pour un provider/mois
│
├── data/              # Volume Docker — persisté sur le Mac
│   ├── factures.db
│   └── pdfs/YYYY-MM/
│
└── tests/
    ├── conftest.py
    ├── test_storage.py
    ├── test_mailer.py
    ├── test_ovh.py
    └── test_scaleway.py
```

---

## Interfaces clés

### `providers/base.py`
```python
@dataclass
class Invoice:
    provider: str       # "ovh", "scaleway", "qonto", etc.
    invoice_id: str     # clé de dédup (UNIQUE dans SQLite)
    issue_date: date
    amount: float
    currency: str       # "EUR"
    pdf_url: str | None
    pdf_path: Path | None
    raw: dict = field(default_factory=dict)

class InvoiceProvider(ABC):
    name: str
    def list_invoices(self, since: date) -> list[Invoice]: ...
    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path: ...
    def is_enabled(self) -> bool: return True
```

---

## Schéma SQLite (`storage.py`)

```sql
sent_invoices (provider, invoice_id UNIQUE, issue_date, amount, currency,
               pdf_path, emailed_at, email_to, created_at)
run_log       (started_at, finished_at, status, providers_ok JSON,
               providers_err JSON, invoices_new, invoices_sent, error_message)
oauth2_tokens (provider PK, access_token, refresh_token, expires_at, scope)
```

**Idempotence** : avant envoi → `SELECT 1 WHERE provider=? AND invoice_id=?`  
**Crash-safe** : insert avec `emailed_at=NULL` après download, update après envoi Mailjet réussi.  
**Prochain run** : les lignes `emailed_at IS NULL` sont renvoyées automatiquement.

---

## OAuth2 — points d'attention

- **Qonto** : access token 1h, refresh token 90 jours. `scripts/setup_qonto.py` effectue le flow authorization_code une fois. `oauth2/refresher.py` rafraîchit avant chaque run. Si le refresh token expire (> 90j sans run), l'erreur est remontée clairement.
- **Microsoft 365** : client_credentials flow, pas de refresh token — nouveau token à chaque run via `POST /oauth2/v2.0/token`. Une app registration par tenant.
- **Atlassian** : OAuth2 2LO (service account), token valide 60 min, rafraîchissement via `refresher.py`.
- **Infomaniak** : token Bearer à durée illimitée depuis le dashboard — pas de refresh nécessaire.

---

## Docker

```dockerfile
FROM python:3.11-slim
# Playwright (uniquement si FREE_MOBILE_ENABLED ou STARLINK_ENABLED)
# providers Playwright isolés derrière feature flags pour garder l'image légère
```

```yaml
# docker-compose.yml
services:
  factures2tiime:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data    # SQLite + PDFs persistent sur le Mac
    restart: unless-stopped
    platform: linux/arm64   # Mac M-series
```

**Scheduler** : APScheduler `CronTrigger(day=3, hour=6, timezone="Europe/Paris")` avec `misfire_grace_time=86400` (rattrapage si le container était éteint).

---

## Configuration `.env.example`

```env
# Scheduler
COLLECTION_DAY=3
COLLECTION_HOUR=6
LOOKBACK_DAYS=40

# Mailjet (envoi vers Tiime)
MAILJET_API_KEY=
MAILJET_SECRET_KEY=
MAIL_FROM=factures@votredomaine.com
TIIME_EMAIL=justif+kysoe@tiime.fr

# OVH
OVH_ENDPOINT=ovh-eu
OVH_APP_KEY=
OVH_APP_SECRET=
OVH_CONSUMER_KEY=

# Scaleway
SCW_AUTH_TOKEN=
SCW_ORG_ID=

# Microsoft 365 — Tenant 1
MS365_TENANT1_ID=
MS365_TENANT1_CLIENT_ID=
MS365_TENANT1_SECRET=
MS365_TENANT1_BILLING_ACCOUNT=

# Microsoft 365 — Tenant 2
MS365_TENANT2_ID=
MS365_TENANT2_CLIENT_ID=
MS365_TENANT2_SECRET=
MS365_TENANT2_BILLING_ACCOUNT=

# Qonto
QONTO_CLIENT_ID=
QONTO_CLIENT_SECRET=

# Infomaniak
INFOMANIAK_API_TOKEN=
INFOMANIAK_ACCOUNT_ID=

# Atlassian
ATLASSIAN_CLIENT_ID=
ATLASSIAN_CLIENT_SECRET=
ATLASSIAN_ACCOUNT_ID=

# Playwright providers (opt-in)
FREE_MOBILE_ENABLED=false
FREE_MOBILE_USER=
FREE_MOBILE_PASS=
STARLINK_ENABLED=false
STARLINK_EMAIL=
STARLINK_PASS=
```

---

## Liste d'étapes

### Phase 1 — Socle

- [ ] **1.1** Créer `.gitignore` (exclure `.env`, `data/`, `__pycache__/`)
- [ ] **1.2** Créer `requirements.txt` (requests, python-dotenv, apscheduler, ovh, playwright, pytest, pytest-mock, responses, mailjet-rest)
- [ ] **1.3** Créer `.env.example` avec toutes les variables documentées
- [ ] **1.4** Créer `config.py` — chargement de toutes les env vars via python-dotenv
- [ ] **1.5** Créer `providers/base.py` — dataclass `Invoice` + ABC `InvoiceProvider` + `ProviderError`
- [ ] **1.6** Créer `storage.py` — schéma SQLite (3 tables), `init_db()`, `db_cursor()`, helpers dedup
- [ ] **1.7** Créer `mailer.py` — Mailjet API `POST /v3.1/send`, un email par facture avec PDF attaché
- [ ] **1.8** Créer `collector.py` — orchestrateur : `run_collection()`, boucle providers, dedup, download, send
- [ ] **1.9** Créer `main.py` — APScheduler CronTrigger + `init_db()` + `validate_config()` au démarrage
- [ ] **1.10** Créer `Dockerfile` — python:3.11-slim, platform linux/arm64
- [ ] **1.11** Créer `docker-compose.yml` — volume `./data:/app/data`, env_file, restart unless-stopped

### Phase 2 — Providers avec API complète

- [ ] **2.1** Créer `providers/ovh.py` — `/me/bill`, download `pdfUrl`, auth ovh-python-sdk
- [ ] **2.2** Créer `providers/scaleway.py` — `/billing/v2beta1/invoices`, download `/download`, X-Auth-Token
- [ ] **2.3** Créer `providers/infomaniak.py` — `/1/invoicing/{id}/invoice-pdf`, Bearer token
- [ ] **2.4** Créer `providers/microsoft365.py` — Azure Billing REST, 2 tenants, client_credentials OAuth2
- [ ] **2.5** Créer `oauth2/token_store.py` — lecture/écriture table `oauth2_tokens` dans SQLite
- [ ] **2.6** Créer `oauth2/refresher.py` — refresh générique access token (Qonto 1h, Atlassian 60min)
- [ ] **2.7** Créer `providers/qonto.py` — `/v2/client_invoices` + attachments, OAuth2 + refresh
- [ ] **2.8** Créer `scripts/setup_qonto.py` — authorization_code flow one-shot (ouvre navigateur)
- [ ] **2.9** Créer `providers/atlassian.py` — Commerce API `/v1/invoices/{id}/download`, OAuth2 2LO

### Phase 3 — Providers Playwright (opt-in)

- [ ] **3.1** Mettre à jour `Dockerfile` pour inclure Chromium/Playwright (conditionnel)
- [ ] **3.2** Créer `providers/free_mobile.py` — Playwright, login portal, download PDF facture
- [ ] **3.3** Créer `providers/starlink.py` — Playwright, login portal, download PDF facture

### Phase 4 — Stubs + scripts utilitaires

- [ ] **4.1** Créer `providers/stubs.py` — stubs Google, Apple, Anthropic, Alan, Mailjet, YouTube (`is_enabled()` → False)
- [ ] **4.2** Créer `scripts/run_now.py` — déclenche `run_collection()` immédiatement sans scheduler
- [ ] **4.3** Créer `scripts/reset_state.py` — efface `sent_invoices` pour un provider/mois donné

### Phase 5 — Tests

- [ ] **5.1** Créer `tests/conftest.py` — fixtures SQLite in-memory, mock Mailjet
- [ ] **5.2** Créer `tests/test_storage.py` — dedup, insert, mark_sent, run_log
- [ ] **5.3** Créer `tests/test_mailer.py` — mock Mailjet API, vérif payload et attachement
- [ ] **5.4** Créer `tests/test_ovh.py` — mock HTTP responses, liste + download
- [ ] **5.5** Créer `tests/test_scaleway.py` — mock HTTP responses, pagination + download

---

## Vérification end-to-end

1. `docker compose build` → image construite sans erreur
2. `docker compose run --rm factures2tiime python scripts/run_now.py` → exécution manuelle
3. Vérifier `data/factures.db` : table `sent_invoices` peuplée, `emailed_at` non null
4. Vérifier `data/pdfs/YYYY-MM/` : PDFs présents
5. Vérifier boîte Tiime : emails reçus avec PDF en pièce jointe
6. Relancer `run_now.py` → aucun doublon envoyé (idempotence)
