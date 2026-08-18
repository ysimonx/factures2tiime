import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# ─── Scheduler ───
COLLECTION_DAY = int(os.getenv("COLLECTION_DAY", "3"))
COLLECTION_HOUR = int(os.getenv("COLLECTION_HOUR", "6"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "40"))

# ─── Mailjet ───
MAILJET_API_KEY = os.getenv("MAILJET_API_KEY")
MAILJET_SECRET_KEY = os.getenv("MAILJET_SECRET_KEY")
MAIL_FROM = os.getenv("MAIL_FROM")
TIIME_EMAIL = os.getenv("TIIME_EMAIL", "justif+kysoe@tiime.fr")
MAIL_CC = os.getenv("MAIL_CC")

# ─── OVH ───
OVH_ENDPOINT = os.getenv("OVH_ENDPOINT", "ovh-eu")
OVH_APP_KEY = os.getenv("OVH_APP_KEY")
OVH_APP_SECRET = os.getenv("OVH_APP_SECRET")
OVH_CONSUMER_KEY = os.getenv("OVH_CONSUMER_KEY")

# ─── Scaleway ───
SCW_AUTH_TOKEN = os.getenv("SCW_AUTH_TOKEN")
SCW_ORG_ID = os.getenv("SCW_ORG_ID")

# ─── Microsoft 365 — Tenant 1 ───
MS365_TENANT1_ID = os.getenv("MS365_TENANT1_ID")
MS365_TENANT1_CLIENT_ID = os.getenv("MS365_TENANT1_CLIENT_ID")
MS365_TENANT1_SECRET = os.getenv("MS365_TENANT1_SECRET")
MS365_TENANT1_BILLING_ACCOUNT = os.getenv("MS365_TENANT1_BILLING_ACCOUNT")

# ─── Microsoft 365 — Tenant 2 ───
MS365_TENANT2_ID = os.getenv("MS365_TENANT2_ID")
MS365_TENANT2_CLIENT_ID = os.getenv("MS365_TENANT2_CLIENT_ID")
MS365_TENANT2_SECRET = os.getenv("MS365_TENANT2_SECRET")
MS365_TENANT2_BILLING_ACCOUNT = os.getenv("MS365_TENANT2_BILLING_ACCOUNT")

# ─── Qonto ───
# OAuth2 (mode recommandé, refresh token ~90 jours) — voir scripts/setup_qonto.py
QONTO_CLIENT_ID = os.getenv("QONTO_CLIENT_ID")
QONTO_CLIENT_SECRET = os.getenv("QONTO_CLIENT_SECRET")
QONTO_REDIRECT_URI = os.getenv("QONTO_REDIRECT_URI", "http://localhost:8080/callback")
# organization.read couvre la liste des transactions, attachment.read les
# justificatifs, offline_access donne le refresh token (sinon le jeton meurt en 1h).
QONTO_SCOPES = os.getenv(
    "QONTO_SCOPES", "offline_access organization.read attachment.read"
)

# ─── Qonto — justificatifs attachés aux transactions ───
QONTO_ATTACHMENTS_ENABLED = (
    os.getenv("QONTO_ATTACHMENTS_ENABLED", "false").lower() == "true"
)
# Commerçants déjà couverts par un provider dédié : leurs justificatifs seraient
# envoyés deux fois à Tiime. Comparaison insensible à la casse, en sous-chaîne.
QONTO_ATTACHMENTS_SKIP = [
    s.strip().lower()
    for s in os.getenv(
        "QONTO_ATTACHMENTS_SKIP",
        "ovh,scaleway,microsoft,google,atlassian,infomaniak,alan,mailjet,"
        "anthropic,mistral,certigna,clockify,starlink,youprice,apple,pokawa,"
        "github",
    ).split(",")
    if s.strip()
]
# Clé API historique (en-tête « login:secret ») — repli si pas d'OAuth
QONTO_LOGIN = os.getenv("QONTO_LOGIN")
QONTO_SECRET_KEY = os.getenv("QONTO_SECRET_KEY")

# ─── Infomaniak ───
INFOMANIAK_API_TOKEN = os.getenv("INFOMANIAK_API_TOKEN")
INFOMANIAK_ACCOUNT_ID = os.getenv("INFOMANIAK_ACCOUNT_ID")

# ─── Atlassian ───
ATLASSIAN_CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
ATLASSIAN_CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
ATLASSIAN_ACCOUNT_ID = os.getenv("ATLASSIAN_ACCOUNT_ID")

# ─── Gmail (OTP Starlink + factures reçues par mail) ───
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8081/callback")

# Alias du compte Gmail secondaire (factures perso : Apple…). Les tokens sont
# stockés sous cet alias — autoriser avec: python scripts/setup_gmail.py --account <alias>
GMAIL_PERSO_ACCOUNT = os.getenv("GMAIL_PERSO_ACCOUNT", "gmail_perso")

# ─── IMAP (boîte non-Gmail : factures Pokawa…) ───
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")

# ─── Pokawa (mail simple, sans PDF → rendu en PDF) ───
POKAWA_ENABLED = os.getenv("POKAWA_ENABLED", "false").lower() == "true"
POKAWA_SENDER = os.getenv("POKAWA_SENDER", "info@belorder.com")

# ─── Apple (reçus d'abonnement sur la boîte Gmail perso) ───
APPLE_MAIL_ENABLED = os.getenv("APPLE_MAIL_ENABLED", "false").lower() == "true"

# ─── Izivia / EDF business services (boîte Gmail perso) ───
IZIVIA_MAIL_ENABLED = os.getenv("IZIVIA_MAIL_ENABLED", "false").lower() == "true"

# ─── GitHub (reçus de paiement sur la boîte Gmail perso, PDF joint) ───
GITHUB_MAIL_ENABLED = os.getenv("GITHUB_MAIL_ENABLED", "false").lower() == "true"

# ─── Playwright providers ───
FREE_MOBILE_ENABLED = os.getenv("FREE_MOBILE_ENABLED", "false").lower() == "true"
FREE_MOBILE_USER = os.getenv("FREE_MOBILE_USER")
FREE_MOBILE_PASS = os.getenv("FREE_MOBILE_PASS")

STARLINK_ENABLED = os.getenv("STARLINK_ENABLED", "false").lower() == "true"
STARLINK_EMAIL = os.getenv("STARLINK_EMAIL")
STARLINK_PASS = os.getenv("STARLINK_PASS")

# YouPrice : espace client protégé par un code à usage unique envoyé par mail,
# lu dans la boîte Gmail principale (comme Starlink).
YOUPRICE_ENABLED = os.getenv("YOUPRICE_ENABLED", "false").lower() == "true"
YOUPRICE_USER = os.getenv("YOUPRICE_USER")
YOUPRICE_PASS = os.getenv("YOUPRICE_PASS")

# Sosh : la facture est dans l'espace client Orange, le mail n'est qu'un avis.
# Identifiants du compte Orange (souvent une adresse @orange.fr / @wanadoo.fr).
SOSH_ENABLED = os.getenv("SOSH_ENABLED", "false").lower() == "true"
SOSH_USER = os.getenv("SOSH_USER")
SOSH_PASS = os.getenv("SOSH_PASS")

# ─── Storage ───
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).expanduser()
DB_PATH = DATA_DIR / "factures.db"
PDF_DIR = DATA_DIR / "pdfs"


def validate_config() -> list[str]:
    """Return list of missing required env vars for enabled providers."""
    missing = []

    if not MAILJET_API_KEY:
        missing.append("MAILJET_API_KEY")
    if not MAILJET_SECRET_KEY:
        missing.append("MAILJET_SECRET_KEY")
    if not MAIL_FROM:
        missing.append("MAIL_FROM")

    return missing
