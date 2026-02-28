import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import load_config
from bot.handlers import start, help_cmd, set_icp, show_icp, photo_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal health check handler for Cloud Run."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass  # Suppress request logs


def _start_health_server(port: int) -> None:
    """Start a background HTTP server for Cloud Run health checks."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health check server started on port %d", port)


def main() -> None:
    config = load_config()

    app = ApplicationBuilder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("seticp", set_icp))
    app.add_handler(CommandHandler("showicp", show_icp))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    if config.webhook_url:
        # Webhook mode for Cloud Run / serverless platforms
        webhook_path = "/webhook"
        logger.info(
            "Starting in webhook mode on port %d -> %s%s",
            config.port,
            config.webhook_url,
            webhook_path,
        )
        app.run_webhook(
            listen="0.0.0.0",
            port=config.port,
            url_path=webhook_path,
            webhook_url=f"{config.webhook_url}{webhook_path}",
        )
    elif os.getenv("K_SERVICE"):
        # Running on Cloud Run but WEBHOOK_URL not set yet (first deploy).
        # Start a health check server so the container becomes healthy,
        # then use polling mode until WEBHOOK_URL is configured.
        logger.info(
            "Cloud Run detected but WEBHOOK_URL not set. "
            "Starting health server + polling mode. "
            "Set WEBHOOK_URL env var to switch to webhook mode."
        )
        _start_health_server(config.port)
        app.run_polling()
    else:
        # Local development
        logger.info("Starting in polling mode...")
        app.run_polling()


if __name__ == "__main__":
    main()
