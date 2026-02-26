import base64
import json
import logging
from dataclasses import dataclass

import anthropic

from bot.config import Config

logger = logging.getLogger(__name__)

VISION_PROMPT = """\
You are analyzing a photo taken at a conference or trade show. The photo shows \
exhibition booths, banners, or displays with company logos and names.

Your task:
1. Identify every distinct company name or logo visible in the photo.
2. For each company, provide:
   - The company name (as accurately as you can read it)
   - A brief note on what you can see about them from the booth \
(tagline, product category, etc.), or "unknown" if nothing is visible.

Return your response as a JSON array. Example:
[
  {"name": "Snowflake", "booth_context": "Cloud data platform, tagline: 'Mobilize your data'"},
  {"name": "Datadog", "booth_context": "Monitoring and security platform"},
  {"name": "Acme Corp", "booth_context": "unknown"}
]

Rules:
- Only include companies you can actually read or recognize in the image.
- Do not guess or hallucinate company names you cannot see.
- If you cannot identify any companies, return an empty array: []
- Return ONLY the JSON array, no other text.
"""


@dataclass
class CompanyInfo:
    name: str
    booth_context: str


async def analyze_photo(config: Config, image_bytes: bytes) -> list[CompanyInfo]:
    """Send photo to Claude Vision API and extract company names/logos."""
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    message = await client.messages.create(
        model=config.claude_model,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                ],
            }
        ],
    )

    raw_text = message.content[0].text.strip()

    # Strip markdown code blocks if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse vision response as JSON: %s", raw_text)
        return []

    companies = []
    for item in data[: config.max_companies_per_photo]:
        companies.append(
            CompanyInfo(
                name=item.get("name", "Unknown"),
                booth_context=item.get("booth_context", "unknown"),
            )
        )

    logger.info("Vision identified %d companies", len(companies))
    return companies
