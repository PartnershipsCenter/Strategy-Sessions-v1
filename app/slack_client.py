import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

logger = logging.getLogger(__name__)


class SlackClient:
    def __init__(self, token: str):
        self._client = WebClient(token=token)
        self._client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))

    def find_channel_by_name(self, name: str) -> str | None:
        """Return the channel ID if it exists, None otherwise."""
        try:
            cursor = None
            while True:
                resp = self._client.conversations_list(
                    types="public_channel,private_channel",
                    limit=200,
                    cursor=cursor,
                )
                for ch in resp["channels"]:
                    if ch["name"] == name:
                        return ch["id"]
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except SlackApiError as e:
            raise RuntimeError(f"Failed to list channels: {e.response['error']}") from e
        return None

    def create_channel(self, name: str = "meeting-summaries") -> str:
        """Create a channel if it doesn't exist. Returns the channel ID."""
        existing = self.find_channel_by_name(name)
        if existing:
            logger.info("Channel #%s already exists: %s", name, existing)
            return existing

        try:
            resp = self._client.conversations_create(name=name)
            channel_id = resp["channel"]["id"]
            logger.info("Created channel #%s: %s", name, channel_id)
            return channel_id
        except SlackApiError as e:
            if e.response["error"] == "name_taken":
                found = self.find_channel_by_name(name)
                if found:
                    return found
            raise RuntimeError(f"Failed to create channel: {e.response['error']}") from e

    def post_message(self, channel_id: str, blocks: list[dict], fallback_text: str) -> str:
        """Post a Block Kit message. Returns the message timestamp."""
        try:
            resp = self._client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text=fallback_text,
            )
            return resp["ts"]
        except SlackApiError as e:
            raise RuntimeError(f"Failed to post message: {e.response['error']}") from e
