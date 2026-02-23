from datetime import datetime, timezone

from app.summarizer import MeetingSummary


def build_summary_blocks(
    title: str,
    date: str,
    attendees: list[str],
    summary: MeetingSummary,
    drive_link: str | None = None,
) -> list[dict]:
    """Build Slack Block Kit blocks for a meeting summary."""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title[:150], "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Date:*\n{date}"},
                {"type": "mrkdwn", "text": f"*Attendees:*\n{', '.join(attendees) or 'N/A'}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary*\n{_truncate(summary.summary, 2900)}"},
        },
    ]

    if summary.key_decisions:
        decisions = "\n".join(f"  - {d}" for d in summary.key_decisions)
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Key Decisions*\n{_truncate(decisions, 2900)}"},
        })

    if summary.action_items:
        items = "\n".join(
            f"  - *{item.get('owner', 'TBD')}*: {item.get('task', '')}"
            for item in summary.action_items
        )
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Action Items*\n{_truncate(items, 2900)}"},
        })

    if summary.topics_discussed:
        topics = ", ".join(summary.topics_discussed)
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Topics:* {_truncate(topics, 2900)}"},
        })

    # Footer
    footer_parts = [f"Posted by Meeting Summary Bot | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]
    if drive_link:
        footer_parts.append(f"<{drive_link}|View full transcript>")

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": " | ".join(footer_parts)}],
    })

    return blocks


def build_fallback_text(title: str, summary: MeetingSummary) -> str:
    """Build plain-text fallback for notifications."""
    return f"{title}\n\n{summary.summary[:500]}"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
