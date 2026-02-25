import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Find .env relative to this file's parent directory (project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_FILE, override=True)


@dataclass(frozen=True)
class Settings:
    fireflies_api_key: str
    fireflies_webhook_secret: str
    anthropic_api_key: str
    slack_bot_token: str
    google_service_account_key_path: str
    google_drive_user_email: str


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        fireflies_api_key=_require_env("FIREFLIES_API_KEY"),
        fireflies_webhook_secret=_require_env("FIREFLIES_WEBHOOK_SECRET"),
        anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
        slack_bot_token=_require_env("SLACK_BOT_TOKEN"),
        google_service_account_key_path=_require_env("GOOGLE_SERVICE_ACCOUNT_KEY_PATH"),
        google_drive_user_email=_require_env("GOOGLE_DRIVE_USER_EMAIL"),
    )
