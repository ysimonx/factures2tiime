from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Invoice:
    provider: str
    invoice_id: str
    issue_date: date
    amount: float
    currency: str
    pdf_url: str | None
    pdf_path: Path | None
    raw: dict = field(default_factory=dict)


class InvoiceProvider(ABC):
    name: str

    @abstractmethod
    def list_invoices(self, since: date) -> list[Invoice]:
        ...

    @abstractmethod
    def fetch_pdf(self, invoice: Invoice, dest_dir: Path) -> Path:
        ...

    def is_enabled(self) -> bool:
        return True


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
