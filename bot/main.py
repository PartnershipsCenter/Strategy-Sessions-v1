import logging

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


def main() -> None:
    config = load_config()

    app = ApplicationBuilder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("seticp", set_icp))
    app.add_handler(CommandHandler("showicp", show_icp))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    logger.info("Booth Scanner Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
