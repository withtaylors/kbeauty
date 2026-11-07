import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kbeauty.catalog import Catalog, load_rules  # noqa: E402
from kbeauty.config import PACKAGE_DIR  # noqa: E402


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog.load(PACKAGE_DIR / "products.json")


@pytest.fixture(scope="session")
def rules():
    return load_rules(PACKAGE_DIR / "rules.json")


@pytest.fixture()
def client(monkeypatch):
    """TestClient against a throw-away DB with vision and live search disabled, whatever is in .env."""
    monkeypatch.setenv("KBEAUTY_IGNORE_DOTENV", "1")
    monkeypatch.setenv("KBEAUTY_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LIVE_FX", "0")                      # tests never touch the network
    from fastapi.testclient import TestClient

    import app as appmod
    with TestClient(appmod.app) as c:
        yield c
