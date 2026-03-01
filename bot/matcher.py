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
    russian_speaking_leaders: str = ""  # Names/roles of likely CIS-origin execs
    search_failed: bool = False


MATCHER_PROMPT_TEMPLATE = """\
You are a sales intelligence assistant. A user has defined their Ideal Customer \
Profile (ICP) and has encountered companies at a conference. For each company, \
you have research data, leadership team information, AND founder biographical data. \
Score how well each company matches the ICP.

## User's ICP:
{icp}

## Companies Found:
{companies_json}

## Instructions:
For each company, provide:
1. "score": integer from 1 to 10 (10 = perfect ICP match)
2. "match_reason": 1-2 sentences explaining why this score, including ICP fit \
AND any CIS-origin leadership signals found
3. "summary": one sentence describing what the company does
4. "russian_speaking_leaders": a short string listing any executives who likely \
speak Russian or come from CIS countries. Format: "Name (Role) - evidence". \
If none found, use empty string "".

## CIS-Origin / Russian-Speaking Executive Detection:
Analyze BOTH the leadership_info AND founder_background fields for each company. \
These are executives from CIS countries (Russia, Ukraine, Belarus, Armenia, Georgia, \
Kazakhstan, Uzbekistan, etc.) who now live and work ANYWHERE in the world. They are \
global professionals in the diaspora.

Look for these signals, in order of strength:

### STRONG signals (high confidence):
- **Explicit language/origin mentions**: "speaks Russian", "born in Moscow", \
"grew up in Tbilisi", "moved from Kyiv", "emigrated from Belarus"
- **CIS university education**: MSU/MGU, MIPT, HSE (Higher School of Economics), \
Bauman, ITMO, Novosibirsk State, Tomsk State, Ural Federal, Kyiv Polytechnic (KPI), \
Taras Shevchenko (Kyiv), Belarusian State (BSU), Yerevan State, Tbilisi State, \
Nazarbayev University, KIMEP, Tashkent, or ANY university located in a CIS country
- **Career history in CIS**: Early career at companies like Yandex, Mail.ru, Kaspersky, \
JetBrains, VK, Ozon, Wildberries, Wargaming, EPAM, Luxoft, or any CIS-based company

### MODERATE signals (medium confidence):
- **Russian/Slavic names**: Sergey, Dmitry, Andrey, Alexey, Mikhail, Vladimir, Igor, \
Oleg, Maxim, Artem, Pavel, Nikita, Anastasia, Natalia, Ekaterina, Olga, Tatiana, \
Elena, Irina. Last names: -ov/-ova, -ev/-eva, -in/-ina, -sky/-skaya, -uk/-chuk, -enko
- **Armenian names**: Aram, Armen, Tigran, Gagik, Hovhannes, Ashot, Hayk, Karen, \
Levon, Vardan. Last names: -yan, -ian (Grigoryan, Petrosyan, Hakobyan, Sargsyan)
- **Georgian names**: Giorgi, Nika, Lasha, Dato, Irakli, Zurab, Giga, Nino, Tamara. \
Last names: -shvili, -dze, -adze (Giorgadze, Beridze, Chikovani)
- **Common Jewish-Russian names**: Lev, Boris, Mark, Ilya, Arkady, Semyon, Roman, \
Grigory, Felix, Eduard. Last names: Levin, Shapiro, Rabinovich, Goldberg, Friedman, \
Kaplan, Brodsky, Reznikov, Berman, Vainberg

### WEAK signals (only if combined with other evidence):
- **Ambiguous Slavic-sounding names** that could be Polish, Czech, Serbian, etc.
- **First name only matches** with no other supporting evidence

When CIS-origin leaders are detected with STRONG or MODERATE signals, \
boost the score by 1-3 points. Mention the specific people and evidence in \
match_reason. Be specific about WHY you think someone is CIS-origin.

IMPORTANT: These are diaspora executives — they live outside CIS countries. \
Do NOT penalize for being based in London, SF, Berlin, etc. That's expected.

Return a JSON array sorted by score descending. Example:
[
  {{"name": "ExampleCorp", "score": 9, "match_reason": "B2B SaaS, 200 employees, \
3 offices globally. CTO Armen Petrosyan (Armenian surname -yan) studied at Yerevan State \
before Stanford MBA — strong CIS-origin signal.", \
"summary": "Cloud data pipeline platform.", \
"russian_speaking_leaders": "Armen Petrosyan (CTO) - Armenian surname, Yerevan State education"}},
  {{"name": "OtherInc", "score": 3, "match_reason": "Consumer app, single location. \
No CIS-origin leadership signals found.", "summary": "Mobile gaming studio.", \
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
                "founder_background": c.founder_background[:1000],
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
