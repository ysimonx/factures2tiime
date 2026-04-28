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
QONTO_LOGIN = os.getenv("QONTO_LOGIN")
QONTO_SECRET_KEY = os.getenv("QONTO_SECRET_KEY")

# ─── Infomaniak ───
INFOMANIAK_API_TOKEN = os.getenv("INFOMANIAK_API_TOKEN")
INFOMANIAK_ACCOUNT_ID = os.getenv("INFOMANIAK_ACCOUNT_ID")

# ─── Atlassian ───
ATLASSIAN_CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
ATLASSIAN_CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
ATLASSIAN_ACCOUNT_ID = os.getenv("ATLASSIAN_ACCOUNT_ID")

# ─── Gmail (OTP Starlink) ───
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8081/callback")

# ─── Playwright providers ───
FREE_MOBILE_ENABLED = os.getenv("FREE_MOBILE_ENABLED", "false").lower() == "true"
FREE_MOBILE_USER = os.getenv("FREE_MOBILE_USER")
FREE_MOBILE_PASS = os.getenv("FREE_MOBILE_PASS")

STARLINK_ENABLED = os.getenv("STARLINK_ENABLED", "false").lower() == "true"
STARLINK_EMAIL = os.getenv("STARLINK_EMAIL")
STARLINK_PASS = os.getenv("STARLINK_PASS")

# ─── Storage ───
DB_PATH = BASE_DIR / "data" / "factures.db"
PDF_DIR = BASE_DIR / "data" / "pdfs"


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
