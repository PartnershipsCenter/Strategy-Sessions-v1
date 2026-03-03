"""Telegram bot command handlers.

Supports two pipelines:
1. Photo pipeline: photo -> vision -> search -> match -> respond
2. Scan pipeline: URL -> scrape -> enrich -> score -> respond
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.config import Config
from core.pipeline import run_pipeline
from bot.vision import analyze_photo
from bot.search import research_companies
from bot.matcher import score_companies
from bot.formatter import (
    format_results, format_scan_results,
    format_no_icp_warning, format_error,
)
from bot.icp_store import get_icp, save_icp

logger = logging.getLogger(__name__)


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["config"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to Conference Scanner Bot!\n\n"
        "I can help you in two ways:\n"
        "1. Send me a photo of conference booths — I'll identify and score the companies\n"
        "2. Use /scan <URL> — I'll scrape an exhibitor list and score all exhibitors\n\n"
        "First, set your ICP with /seticp\n"
        "Example: /seticp B2B SaaS, 50-500 employees, Series A+, "
        "cloud infrastructure / data / AI"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/seticp <description> - Set your ideal customer profile\n"
        "/showicp - Show your current ICP\n"
        "/scan <URL> - Scan a conference exhibitor list\n"
        "/help - Show this message\n\n"
        "You can also send a photo of conference booths for instant analysis."
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


async def scan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scan a conference exhibitor list URL."""
    config = _get_config(context)
    user_id = update.effective_user.id

    # Check ICP exists
    icp = await get_icp(config.db_path, user_id)
    if not icp:
        await update.message.reply_text(format_no_icp_warning())
        return

    # Extract URL from command
    text = update.message.text.replace("/scan", "", 1).strip()
    if not text:
        await update.message.reply_text(
            "Please provide a URL after /scan.\n"
            "Example: /scan https://www.mwcbarcelona.com/exhibitors"
        )
        return

    url = text.split()[0]  # Take first word as URL
    if not url.startswith("http"):
        url = "https://" + url

    status_msg = await update.message.reply_text(
        f"Starting conference scan...\n"
        f"URL: {url}\n"
        f"This may take several minutes for large exhibitor lists."
    )

    # Progress callback — edit the status message
    last_stage = {"value": ""}

    async def progress_callback(
        stage: str, message: str, current: int, total: int
    ) -> None:
        nonlocal last_stage
        try:
            # Only update if stage changed or significant progress
            if stage != last_stage["value"] or (current > 0 and current % 10 == 0):
                last_stage["value"] = stage
                progress_text = f"Stage: {stage}\n{message}"
                if total > 0:
                    progress_text += f"\n({current}/{total})"
                await status_msg.edit_text(progress_text)
        except Exception:
            pass  # Ignore edit failures (rate limits, etc.)

    try:
        result = await run_pipeline(
            config=config,
            url=url,
            icp=icp,
            on_progress=progress_callback,
        )

        if result.error:
            await status_msg.edit_text(f"Scan failed: {result.error}")
            return

        if not result.results:
            await status_msg.edit_text(
                "Scan completed but no exhibitors were found. "
                "The page may require login or have a non-standard layout."
            )
            return

        # Format and send results
        result_text = format_scan_results(result.results)

        # Telegram message limit is 4096 chars
        if len(result_text) > 4000:
            # Split into multiple messages
            await status_msg.edit_text(
                f"Scan complete! Found {result.total_exhibitors} exhibitors, "
                f"scored top {result.total_scored}. Sending results..."
            )
            # Send in chunks
            chunks = _split_message(result_text, 4000)
            for chunk in chunks:
                await update.message.reply_text(
                    chunk, parse_mode="MarkdownV2"
                )
        else:
            await status_msg.edit_text(result_text, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in scan pipeline")
        await status_msg.edit_text(format_error(e))


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo pipeline: photo -> vision -> search -> match -> respond."""
    config = _get_config(context)
    user_id = update.effective_user.id

    icp = await get_icp(config.db_path, user_id)
    if not icp:
        await update.message.reply_text(format_no_icp_warning())
        return

    status_msg = await update.message.reply_text(
        "Got your photo! Analyzing booth logos..."
    )

    try:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()

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

        researched = await research_companies(config, companies)
        await status_msg.edit_text("Scoring against your ICP...")
        scored = await score_companies(config, researched, icp)
        result_text = format_results(scored)
        await status_msg.edit_text(result_text, parse_mode="MarkdownV2")

    except Exception as e:
        logger.exception("Error in photo pipeline")
        await status_msg.edit_text(format_error(e))


def _split_message(text: str, max_len: int) -> list[str]:
    """Split a long message into chunks at paragraph boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
                current = line
            else:
                # Single line too long — force split
                chunks.append(line[:max_len])
                current = line[max_len:]
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    return chunks
