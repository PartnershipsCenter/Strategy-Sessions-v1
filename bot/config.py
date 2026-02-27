import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    anthropic_api_key: str
    tavily_api_key: str
    claude_model: str = "claude-sonnet-4-6"
    db_path: str = "data/icp_store.db"
    max_companies_per_photo: int = 15
    # Webhook settings for Cloud Run / serverless deployment
    webhook_url: str = ""  # e.g. "https://my-bot-xyz.run.app"
    port: int = 8080


def load_config() -> Config:
    """Load config from environment variables. Raises ValueError if required vars are missing."""
    required = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return Config(
        telegram_bot_token=required["TELEGRAM_BOT_TOKEN"],
        anthropic_api_key=required["ANTHROPIC_API_KEY"],
        tavily_api_key=required["TAVILY_API_KEY"],
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
        db_path=os.getenv("DB_PATH", "data/icp_store.db"),
        webhook_url=os.getenv("WEBHOOK_URL", ""),
        port=int(os.getenv("PORT", "8080")),
    )
