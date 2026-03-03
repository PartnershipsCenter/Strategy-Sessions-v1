"""ICP scoring pipeline — sends exhibitors to Claude in batches for scoring.

Adapted from the existing bot/matcher.py but works with the new
exhibitor data model and supports batching for large lists.
"""

import json
import logging
from dataclasses import dataclass

import anthropic

from core.config import Config
from core.db import ExhibitorRow, DB

logger = logging.getLogger(__name__)


@dataclass
class ScoredExhibitor:
    """Scoring result for a single exhibitor."""
    exhibitor_id: int
    company_name: str
    score: int
    reasoning: str
    summary: str
    russian_speaking_leaders: str = ""


SCORER_PROMPT = """\
You are a sales intelligence assistant. A user has defined their Ideal Customer \
Profile (ICP) and wants to find the best exhibitors to visit at a conference. \
For each company, score how well it matches the ICP.

## User's ICP:
{icp}

## Companies to Score:
{companies_json}

## Instructions:
For each company, provide:
1. "name": the exact company name as given
2. "score": integer from 1 to 10 (10 = perfect ICP match)
3. "match_reason": 1-2 sentences explaining why this score
4. "summary": one sentence describing what the company does
5. "russian_speaking_leaders": executives who likely speak Russian or come from \
CIS countries. Format: "Name (Role) - evidence". Empty string "" if none found.

## CIS-Origin / Russian-Speaking Executive Detection:
Analyze the leadership_info and founder_background fields for each company. \
Look for CIS diaspora executives (from Russia, Ukraine, Belarus, Armenia, Georgia, \
Kazakhstan, Uzbekistan, etc.) who now work ANYWHERE in the world.

Signals to look for:
- **STRONG**: Explicit origin mentions, CIS university education (MSU, MIPT, HSE, \
Bauman, ITMO, KPI, Yerevan State, Nazarbayev, etc.), early career at CIS companies \
(Yandex, Mail.ru, Kaspersky, JetBrains, EPAM, Luxoft, etc.)
- **MODERATE**: Slavic names (-ov/-ova, -ev/-eva, -sky/-skaya, -enko), Armenian names \
(-yan, -ian), Georgian names (-shvili, -dze)
- **WEAK**: Ambiguous names (only flag if combined with other evidence)

When CIS-origin leaders are detected with STRONG or MODERATE signals, \
boost the score by 1-3 points.

Return a JSON array sorted by score descending. Example:
[
  {{"name": "ExampleCorp", "score": 9, "match_reason": "B2B SaaS, 200 employees. \
CTO Armen Petrosyan studied at Yerevan State.", \
"summary": "Cloud data pipeline platform.", \
"russian_speaking_leaders": "Armen Petrosyan (CTO) - Armenian surname, Yerevan State education"}},
  {{"name": "OtherInc", "score": 3, "match_reason": "Consumer app, not matching ICP.", \
"summary": "Mobile gaming studio.", "russian_speaking_leaders": ""}}
]

If a company has no research data, score based on whatever info is available. \
If zero info, give score 0.
Return ONLY the JSON array.
"""


def _build_company_data(
    exhibitor: ExhibitorRow, enrichment: dict
) -> dict:
    """Build a company data dict for the scoring prompt."""
    return {
        "name": exhibitor.company_name,
        "website": exhibitor.website_url,
        "description": exhibitor.description or enrichment.get("description", ""),
        "categories": exhibitor.categories,
        "booth_location": exhibitor.booth_location,
        "key_facts": enrichment.get("key_facts", [])[:2],
        "leadership_info": enrichment.get("leadership_info", "")[:1000],
        "founder_background": enrichment.get("founder_background", "")[:1000],
    }


async def score_batch(
    config: Config,
    exhibitors: list[ExhibitorRow],
    enrichments: dict[int, dict],
    icp: str,
) -> list[ScoredExhibitor]:
    """Score a batch of exhibitors (max ~20) against the ICP."""
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    companies_data = []
    id_map = {}  # name -> exhibitor_id

    for e in exhibitors:
        enrichment = enrichments.get(e.id, {})
        companies_data.append(_build_company_data(e, enrichment))
        id_map[e.company_name.lower()] = e.id

    prompt = SCORER_PROMPT.format(
        icp=icp,
        companies_json=json.dumps(companies_data, indent=2),
    )

    try:
        message = await client.messages.create(
            model=config.claude_model_score,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)

    except Exception as e:
        logger.error("Scoring batch failed: %s", e)
        return [
            ScoredExhibitor(
                exhibitor_id=ex.id,
                company_name=ex.company_name,
                score=0,
                reasoning="Scoring unavailable",
                summary=ex.description[:100] if ex.description else "",
            )
            for ex in exhibitors
        ]

    scored = []
    for item in data:
        name = item.get("name", "")
        exhibitor_id = id_map.get(name.lower(), 0)
        if not exhibitor_id:
            # Fuzzy match
            for key, eid in id_map.items():
                if name.lower() in key or key in name.lower():
                    exhibitor_id = eid
                    break

        scored.append(ScoredExhibitor(
            exhibitor_id=exhibitor_id,
            company_name=name,
            score=min(max(item.get("score", 0), 0), 10),
            reasoning=item.get("match_reason", ""),
            summary=item.get("summary", ""),
            russian_speaking_leaders=item.get("russian_speaking_leaders", ""),
        ))

    return scored


async def score_all_exhibitors(
    config: Config,
    db: DB,
    conference_id: int,
    icp: str,
    on_progress=None,
) -> int:
    """Score all exhibitors for a conference against an ICP.

    Creates a scoring run in the DB, scores in batches of 20,
    and returns the scoring_run_id.
    """
    exhibitors = await db.get_exhibitors(conference_id)
    if not exhibitors:
        return 0

    scoring_run_id = await db.create_scoring_run(conference_id, icp)
    total = len(exhibitors)
    batch_size = 20
    scored_count = 0

    # Build enrichment lookup
    enrichments = {}
    for e in exhibitors:
        enrichments[e.id] = {
            "description": e.description,
            "key_facts": [],
            **(e.enrichment_data if e.enrichment_data else {}),
        }

    for i in range(0, total, batch_size):
        batch = exhibitors[i : i + batch_size]

        if on_progress:
            await on_progress(
                "score",
                f"Scoring batch {i // batch_size + 1} "
                f"({min(i + batch_size, total)}/{total})...",
                min(i + batch_size, total),
                total,
            )

        results = await score_batch(config, batch, enrichments, icp)

        for result in results:
            if result.exhibitor_id:
                await db.save_scored_exhibitor(
                    scoring_run_id=scoring_run_id,
                    exhibitor_id=result.exhibitor_id,
                    score=result.score,
                    reasoning=result.reasoning,
                    summary=result.summary,
                    russian_speaking_leaders=result.russian_speaking_leaders,
                )
                scored_count += 1

    await db.complete_scoring_run(scoring_run_id, scored_count)

    if on_progress:
        await on_progress(
            "score",
            f"Scoring complete! {scored_count} exhibitors scored.",
            scored_count,
            scored_count,
        )

    return scoring_run_id
