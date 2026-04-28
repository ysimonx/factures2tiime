import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use in-memory SQLite for all tests
os.environ.setdefault("MAILJET_API_KEY", "test_key")
os.environ.setdefault("MAILJET_SECRET_KEY", "test_secret")
os.environ.setdefault("MAIL_FROM", "test@example.com")
os.environ.setdefault("TIIME_EMAIL", "test-tiime@example.com")


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    """Redirect DB and PDF paths to a temp dir for every test."""
    import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "PDF_DIR", tmp_path / "pdfs")
    import storage
    storage.init_db()
    yield
