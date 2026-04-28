"""
Stub providers for services with no invoice API.
These are placeholders — is_enabled() returns False by default.
To handle these, forward invoices manually to justif+kysoe@tiime.fr
or implement email parsing in a future iteration.
"""
from datetime import date
from pathlib import Path

from providers.base import Invoice, InvoiceProvider


class _NoApiStub(InvoiceProvider):
    def is_enabled(self) -> bool:
        return False

    def list_invoices(self, since: date) -> list[Invoice]:
        return []

    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        raise NotImplementedError(f"{self.name} has no API — manual forward required")


class GoogleWorkspaceStub(_NoApiStub):
    name = "google_workspace"


class AppleStub(_NoApiStub):
    name = "apple"


class AnthropicStub(_NoApiStub):
    name = "anthropic"


class AlanStub(_NoApiStub):
    name = "alan"


class MailjetStub(_NoApiStub):
    name = "mailjet_billing"


class YoutubeStub(_NoApiStub):
    name = "youtube_premium"


class AtlassianStub(_NoApiStub):
    # Commerce API réservée aux partenaires Atlassian Marketplace — pas accessible aux clients directs
    name = "atlassian"
