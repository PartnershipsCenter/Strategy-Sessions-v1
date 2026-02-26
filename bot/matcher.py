import json
import logging
from dataclasses import dataclass

import anthropic

from bot.config import Config
from bot.search import CompanyResearch

logger = logging.getLogger(__name__)


@dataclass
class ScoredCompany:
    name: str
    score: int
    match_reason: str
    website: str
    summary: str
    search_failed: bool = False


MATCHER_PROMPT_TEMPLATE = """\
You are a sales intelligence assistant. A user has defined their Ideal Customer \
Profile (ICP) and has encountered companies at a conference. For each company, \
you have research data. Score how well each company matches the ICP.

## User's ICP:
{icp}

## Companies Found:
{companies_json}

## Instructions:
For each company, provide:
1. "score": integer from 1 to 10 (10 = perfect ICP match)
2. "match_reason": 1-2 sentences explaining why this score
3. "summary": one sentence describing what the company does

Return a JSON array sorted by score descending. Example:
[
  {{"name": "ExampleCorp", "score": 9, "match_reason": "B2B SaaS in data infra, Series B, 200 employees - strong ICP fit", "summary": "Cloud data pipeline platform for enterprises."}},
  {{"name": "OtherInc", "score": 3, "match_reason": "Consumer app, pre-revenue - does not match B2B or size criteria", "summary": "Mobile gaming studio."}}
]

If a company has search_failed=true, score it based only on any available booth_context. \
If no info at all, give score 0 and note that research was unavailable.
Return ONLY the JSON array.
"""


def _build_companies_json(companies: list[CompanyResearch]) -> str:
    """Serialize company research for the prompt."""
    items = []
    for c in companies:
        items.append(
            {
                "name": c.name,
                "booth_context": c.booth_context,
                "website": c.website,
                "description": c.description,
                "key_facts": c.key_facts[:2],
                "search_failed": c.search_failed,
            }
        )
    return json.dumps(items, indent=2)


async def score_companies(
    config: Config,
    companies: list[CompanyResearch],
    icp: str,
) -> list[ScoredCompany]:
    """Use Claude to score companies against the user's ICP."""
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    companies_json = _build_companies_json(companies)
    prompt = MATCHER_PROMPT_TEMPLATE.format(
        icp=icp,
        companies_json=companies_json,
    )

    message = await client.messages.create(
        model=config.claude_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = message.content[0].text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse matcher response: %s", raw_text)
        return [
            ScoredCompany(
                name=c.name,
                score=0,
                match_reason="Scoring unavailable",
                website=c.website,
                summary=c.description[:100],
                search_failed=c.search_failed,
            )
            for c in companies
        ]

    website_lookup = {c.name.lower(): c.website for c in companies}
    search_failed_lookup = {c.name.lower(): c.search_failed for c in companies}

    scored = []
    for item in data:
        name = item.get("name", "Unknown")
        scored.append(
            ScoredCompany(
                name=name,
                score=item.get("score", 0),
                match_reason=item.get("match_reason", ""),
                website=website_lookup.get(name.lower(), ""),
                summary=item.get("summary", ""),
                search_failed=search_failed_lookup.get(name.lower(), False),
            )
        )

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored
