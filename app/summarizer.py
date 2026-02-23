import json
from dataclasses import dataclass

import anthropic

SUMMARY_SYSTEM_PROMPT = """You are a meeting summary assistant. Given a meeting transcript, produce a structured JSON summary.

Return ONLY valid JSON with this exact structure:
{
  "summary": "2-3 paragraph overview of the meeting",
  "key_decisions": ["decision 1", "decision 2"],
  "action_items": [{"owner": "Person Name", "task": "description of task"}],
  "topics_discussed": ["topic 1", "topic 2"]
}

Be concise but capture all important points. Attribute action items to specific people when possible."""


@dataclass
class MeetingSummary:
    summary: str
    key_decisions: list[str]
    action_items: list[dict]
    topics_discussed: list[str]


async def summarize_transcript(api_key: str, transcript_text: str, title: str) -> MeetingSummary:
    """Use Claude to generate a structured summary of a meeting transcript."""
    client = anthropic.AsyncAnthropic(api_key=api_key)

    user_message = f"Meeting title: {title}\n\nTranscript:\n{transcript_text}"

    # Use streaming to avoid timeouts on long transcripts
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        response = await stream.get_final_message()

    raw = response.content[0].text

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # If Claude wrapped it in markdown code fences, extract the JSON
        if "```" in raw:
            json_str = raw.split("```json")[-1].split("```")[0] if "```json" in raw else raw.split("```")[1].split("```")[0]
            data = json.loads(json_str.strip())
        else:
            raise

    return MeetingSummary(
        summary=data.get("summary", ""),
        key_decisions=data.get("key_decisions", []),
        action_items=data.get("action_items", []),
        topics_discussed=data.get("topics_discussed", []),
    )
