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
    russian_speaking_leaders: str = ""  # Names/roles of likely Russian-speaking execs
    search_failed: bool = False


MATCHER_PROMPT_TEMPLATE = """\
You are a sales intelligence assistant. A user has defined their Ideal Customer \
Profile (ICP) and has encountered companies at a conference. For each company, \
you have research data AND leadership team information. Score how well each \
company matches the ICP.

## User's ICP:
{icp}

## Companies Found:
{companies_json}

## Instructions:
For each company, provide:
1. "score": integer from 1 to 10 (10 = perfect ICP match)
2. "match_reason": 1-2 sentences explaining why this score, including ICP fit \
AND any Russian-speaking leadership signals found
3. "summary": one sentence describing what the company does
4. "russian_speaking_leaders": a short string listing any executives who likely \
speak Russian, based on the evidence below. Format: "Name (Role) - evidence". \
If none found, use empty string "".

## Russian-Speaking Executive Detection:
Analyze the leadership_info field for each company. Look for these signals:
- **Names**: Slavic/Russian first or last names (e.g., Sergey, Dmitry, Anastasia, \
Andrey, Natalia, Mikhail, Ivanov, Petrov, Kozlov, Volkov, Novikov, etc.)
- **Education**: Universities in Russia, Ukraine, Belarus, Kazakhstan, or other \
CIS countries (e.g., MSU/MGU, MIPT, HSE, Bauman, ITMO, Novosibirsk State, \
Kyiv Polytechnic, Belarusian State, etc.)
- **Languages**: Any mention of Russian language proficiency on profiles
- **Location history**: Work or education history in CIS countries

When Russian-speaking leaders are detected, this is a STRONG positive signal. \
Boost the score by 1-2 points. Mention the specific people and evidence in \
match_reason.

Return a JSON array sorted by score descending. Example:
[
  {{"name": "ExampleCorp", "score": 9, "match_reason": "B2B SaaS, 200 employees, \
3 offices globally. CTO Dmitry Volkov (MIPT graduate) likely Russian-speaking.", \
"summary": "Cloud data pipeline platform.", \
"russian_speaking_leaders": "Dmitry Volkov (CTO) - MIPT education, Slavic name"}},
  {{"name": "OtherInc", "score": 3, "match_reason": "Consumer app, single location, \
no Russian-speaking leadership signals found.", "summary": "Mobile gaming studio.", \
"russian_speaking_leaders": ""}}
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
                "leadership_info": c.leadership_info[:1000],
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
                russian_speaking_leaders=item.get("russian_speaking_leaders", ""),
                search_failed=search_failed_lookup.get(name.lower(), False),
            )
        )

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored
