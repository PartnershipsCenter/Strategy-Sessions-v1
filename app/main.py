import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings, load_settings
from app.fireflies_client import fetch_transcript, verify_webhook_signature
from app.google_drive_client import GoogleDriveClient
from app.message_builder import build_fallback_text, build_summary_blocks
from app.slack_client import SlackClient
from app.summarizer import summarize_transcript

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- Shared state initialised at startup ---

settings: Settings
drive_client: GoogleDriveClient
slack_client: SlackClient
slack_channel_id: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global settings, drive_client, slack_client, slack_channel_id

    settings = load_settings()
    drive_client = GoogleDriveClient(settings.google_service_account_key_path)
    slack_client = SlackClient(settings.slack_bot_token)

    # Ensure Slack channel and Drive root folder exist on startup
    slack_channel_id = slack_client.create_channel("meeting-summaries")
    drive_client.ensure_shared_root(settings.google_drive_user_email)

    logger.info("Startup complete — Slack channel: %s", slack_channel_id)
    yield


app = FastAPI(title="Fireflies Transcript Pipeline", lifespan=lifespan)


# ---------- Health check ----------

@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- Fireflies webhook ----------

@app.post("/webhook/fireflies")
async def handle_fireflies_webhook(
    request: Request,
    x_hub_signature: Optional[str] = Header(None),
):
    body = await request.body()

    # 1. Verify webhook signature
    if settings.fireflies_webhook_secret and x_hub_signature:
        if not verify_webhook_signature(body, x_hub_signature, settings.fireflies_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    meeting_id = payload.get("meetingId")
    if not meeting_id:
        raise HTTPException(status_code=400, detail="Missing meetingId in payload")

    event_type = payload.get("eventType", "")
    logger.info("Webhook received — meetingId=%s eventType=%s", meeting_id, event_type)

    # 2. Fetch transcript from Fireflies
    transcript = await fetch_transcript(settings.fireflies_api_key, meeting_id)
    logger.info("Fetched transcript: %s (%d sentences)", transcript.title, len(transcript.sentences))

    # 3. Upload to Google Drive
    now = datetime.now(timezone.utc)
    folder_id = drive_client.ensure_date_folder(now.year, now.month)
    safe_title = transcript.title.replace("/", "-").replace("\\", "-")
    filename = f"{now.strftime('%Y-%m-%d')}_{safe_title}.txt"

    drive_result = drive_client.upload_transcript(folder_id, filename, transcript.full_text)
    drive_link = drive_result.get("webViewLink")
    logger.info("Uploaded to Drive: %s", drive_link)

    # 4. Summarize with Claude
    summary = await summarize_transcript(
        settings.anthropic_api_key, transcript.full_text, transcript.title
    )
    logger.info("Summary generated — %d decisions, %d action items",
                len(summary.key_decisions), len(summary.action_items))

    # 5. Post to Slack
    attendee_names = [a["name"] for a in transcript.attendees if a.get("name")] or transcript.speakers
    blocks = build_summary_blocks(
        title=transcript.title,
        date=transcript.date or now.strftime("%Y-%m-%d"),
        attendees=attendee_names,
        summary=summary,
        drive_link=drive_link,
    )
    fallback = build_fallback_text(transcript.title, summary)
    ts = slack_client.post_message(slack_channel_id, blocks, fallback)
    logger.info("Posted to Slack: ts=%s", ts)

    return {
        "status": "processed",
        "meeting_id": meeting_id,
        "drive_file_id": drive_result.get("id"),
        "slack_ts": ts,
    }


# ---------- Manual setup endpoint (one-time) ----------

@app.post("/setup")
async def setup():
    """One-time setup: create Slack channel and share Drive folder."""
    channel_id = slack_client.create_channel("meeting-summaries")
    root_id = drive_client.ensure_shared_root(settings.google_drive_user_email)
    return {
        "slack_channel_id": channel_id,
        "drive_root_folder_id": root_id,
    }
