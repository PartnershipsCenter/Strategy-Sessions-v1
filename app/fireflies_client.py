import hashlib
import hmac
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

FIREFLIES_GRAPHQL_URL = "https://api.fireflies.ai/graphql"

TRANSCRIPT_QUERY = """
query Transcript($transcriptId: String!) {
  transcript(id: $transcriptId) {
    id
    title
    dateString
    host_email
    duration
    speakers {
      id
      name
    }
    sentences {
      index
      speaker_name
      text
      start_time
      end_time
    }
    meeting_attendees {
      displayName
      email
    }
    summary {
      keywords
      action_items
      outline
      shorthand_bullet
    }
  }
}
"""


@dataclass
class TranscriptData:
    id: str
    title: str
    date: str
    host_email: str
    duration: Optional[float]
    speakers: List[str]
    attendees: List[Dict]
    sentences: List[Dict]
    summary: Dict
    full_text: str


def verify_webhook_signature(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify the x-hub-signature header from Fireflies webhook."""
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def fetch_transcript(api_key: str, meeting_id: str) -> TranscriptData:
    """Fetch a full transcript from Fireflies GraphQL API."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            FIREFLIES_GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": TRANSCRIPT_QUERY,
                "variables": {"transcriptId": meeting_id},
            },
        )
        response.raise_for_status()

    data = response.json()
    if "errors" in data:
        raise RuntimeError(f"Fireflies GraphQL error: {data['errors']}")

    t = data["data"]["transcript"]

    speakers = [s["name"] for s in (t.get("speakers") or [])]
    sentences = t.get("sentences") or []

    # Build full transcript text with speaker labels
    lines = []
    for s in sentences:
        speaker = s.get("speaker_name", "Unknown")
        text = s.get("text", "")
        lines.append(f"{speaker}: {text}")
    full_text = "\n".join(lines)

    attendees = [
        {"name": a.get("displayName", ""), "email": a.get("email", "")}
        for a in (t.get("meeting_attendees") or [])
    ]

    return TranscriptData(
        id=t["id"],
        title=t.get("title", "Untitled Meeting"),
        date=t.get("dateString", ""),
        host_email=t.get("host_email", ""),
        duration=t.get("duration"),
        speakers=speakers,
        attendees=attendees,
        sentences=sentences,
        summary=t.get("summary") or {},
        full_text=full_text,
    )
