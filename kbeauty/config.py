"""Application settings, loaded once from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, '#' comments, existing env wins."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and not os.getenv(key):
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration."""

    db_path: Path = field(default_factory=lambda: Path(os.getenv("KBEAUTY_DB", PROJECT_DIR / "data" / "kbeauty.db")))
    products_path: Path = field(default_factory=lambda: PACKAGE_DIR / "products.json")
    rules_path: Path = field(default_factory=lambda: PACKAGE_DIR / "rules.json")
    static_dir: Path = field(default_factory=lambda: PROJECT_DIR / "static")

    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"))
    vision_timeout_s: float = field(default_factory=lambda: float(os.getenv("VISION_TIMEOUT", "45")))

    naver_client_id: str | None = field(default_factory=lambda: os.getenv("NAVER_CLIENT_ID") or None)
    naver_client_secret: str | None = field(default_factory=lambda: os.getenv("NAVER_CLIENT_SECRET") or None)
    tavily_api_key: str | None = field(default_factory=lambda: os.getenv("TAVILY_API_KEY") or None)
    live_fx: bool = field(default_factory=lambda: os.getenv("LIVE_FX", "1") != "0")
    live_olive_young_only: bool = field(default_factory=lambda: os.getenv("LIVE_OLIVE_YOUNG_ONLY", "1") != "0")

    confidence_threshold: float = 0.7   # below this, the user picks from candidates
    max_image_bytes: int = 6 * 1024 * 1024
    supported_langs: tuple[str, ...] = ("en", "ko")
    supported_currencies: tuple[str, ...] = ("USD", "JPY")

    @property
    def vision_enabled(self) -> bool:
        return bool(self.openai_api_key or self.anthropic_api_key)

    @property
    def live_search_enabled(self) -> bool:
        return bool(self.naver_client_id and self.naver_client_secret)


def get_settings() -> Settings:
    if os.getenv("KBEAUTY_IGNORE_DOTENV") != "1":      # tests set this so a developer's real keys never leak in
        load_dotenv(PROJECT_DIR / ".env")
    return Settings()
