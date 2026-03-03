"""Shared configuration for conference scanner."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Always try to load .env from project root
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(str(_env_file), override=True)


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    tavily_api_key: str
    telegram_bot_token: str = ""
    # Use cheap model for extraction, smart model for scoring
    claude_model_extract: str = "claude-haiku-4-5"
    claude_model_score: str = "claude-sonnet-4-6"
    db_path: str = "data/conference_scanner.db"
    port: int = 8080
    webhook_url: str = ""
    # Scraping settings
    scrape_delay: float = 1.0  # seconds between detail page fetches
    max_detail_pages: int = 1000  # safety cap


def load_config() -> Config:
    """Load config from environment variables."""
    required = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return Config(
        anthropic_api_key=required["ANTHROPIC_API_KEY"],
        tavily_api_key=required["TAVILY_API_KEY"],
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        claude_model_extract=os.getenv("CLAUDE_MODEL_EXTRACT", "claude-haiku-4-5"),
        claude_model_score=os.getenv("CLAUDE_MODEL_SCORE", "claude-sonnet-4-6"),
        db_path=os.getenv("DB_PATH", "data/conference_scanner.db"),
        port=int(os.getenv("PORT", "8080")),
        webhook_url=os.getenv("WEBHOOK_URL", ""),
        scrape_delay=float(os.getenv("SCRAPE_DELAY", "1.0")),
        max_detail_pages=int(os.getenv("MAX_DETAIL_PAGES", "1000")),
    )
