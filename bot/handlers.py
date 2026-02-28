import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Config
from bot.vision import analyze_photo
from bot.search import research_companies
from bot.matcher import score_companies
from bot.formatter import format_results, format_no_icp_warning, format_error
from bot.icp_store import get_icp, save_icp

logger = logging.getLogger(__name__)


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["config"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to Booth Scanner Bot!\n\n"
        "Send me a photo of conference booths and I'll identify the companies, "
        "research them, and tell you which ones match your ideal customer profile.\n\n"
        "First, set your ICP with /seticp\n"
        "Example: /seticp B2B SaaS, 50-500 employees, Series A+, US-based, "
        "needs data infrastructure"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/seticp <description> - Set your ideal customer profile\n"
        "/showicp - Show your current ICP\n"
        "/help - Show this message\n\n"
        "Send a photo of conference booths to get ICP-matched recommendations."
    )


async def set_icp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    text = update.message.text.replace("/seticp", "", 1).strip()
    if not text:
        await update.message.reply_text(
            "Please provide your ICP description after the command.\n"
            "Example: /seticp B2B SaaS, 50-500 employees, Series A+"
        )
        return
    user_id = update.effective_user.id
    await save_icp(config.db_path, user_id, text)
    await update.message.reply_text(f"ICP saved:\n{text}")


async def show_icp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    user_id = update.effective_user.id
    icp = await get_icp(config.db_path, user_id)
    if icp:
        await update.message.reply_text(f"Your current ICP:\n{icp}")
    else:
        await update.message.reply_text("No ICP set yet. Use /seticp to define one.")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main pipeline: photo -> vision -> search -> match -> respond."""
    config = _get_config(context)
    user_id = update.effective_user.id

    # Check ICP exists
    icp = await get_icp(config.db_path, user_id)
    if not icp:
        await update.message.reply_text(format_no_icp_warning())
        return

    status_msg = await update.message.reply_text(
        "Got your photo! Analyzing booth logos..."
    )

    try:
        # Step 1: Download photo (largest available size)
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()

        # Step 2: Vision - identify company logos
        await status_msg.edit_text("Identifying company logos...")
        companies = await analyze_photo(config, bytes(image_bytes))

        if not companies:
            await status_msg.edit_text(
                "I couldn't identify any company logos in this photo. "
                "Try a clearer photo with visible booth signage."
            )
            return

        company_names = [c.name for c in companies]
        await status_msg.edit_text(
            f"Found {len(companies)} companies: {', '.join(company_names)}\n"
            "Researching companies & leadership teams..."
        )

        # Step 3: Web research + leadership research (concurrent)
        researched = await research_companies(config, companies)

        await status_msg.edit_text("Scoring against your ICP...")

        # Step 4: ICP matching & scoring
        scored = await score_companies(config, researched, icp)

        # Step 5: Format and send results
        result_text = format_results(scored)
        await status_msg.edit_text(result_text, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in photo pipeline")
        await status_msg.edit_text(format_error(e))
