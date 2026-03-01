import asyncio
import logging
from dataclasses import dataclass, field

from tavily import AsyncTavilyClient

from bot.config import Config
from bot.vision import CompanyInfo

logger = logging.getLogger(__name__)


@dataclass
class CompanyResearch:
    name: str
    booth_context: str
    website: str = ""
    description: str = ""
    key_facts: list[str] = field(default_factory=list)
    leadership_info: str = ""  # Leadership names, roles, Crunchbase/LinkedIn data
    founder_background: str = ""  # Biographical deep-dive: education, origin, languages
    search_failed: bool = False


async def _search_one_company(
    client: AsyncTavilyClient, company: CompanyInfo
) -> CompanyResearch:
    """Search for a single company and extract structured info."""
    query = f"{company.name} company employees headcount funding"
    if company.booth_context and company.booth_context != "unknown":
        query += f" {company.booth_context}"

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=5,
            include_answer="basic",
        )

        website = ""
        all_content = []
        for result in response.get("results", []):
            url = result.get("url", "")
            company_name_lower = company.name.lower().replace(" ", "")
            if company_name_lower in url.lower() and not website:
                website = url
            content = result.get("content", "")
            if content:
                all_content.append(content)

        answer = response.get("answer", "")
        description = answer if answer else (all_content[0] if all_content else "")

        return CompanyResearch(
            name=company.name,
            booth_context=company.booth_context,
            website=website,
            description=description[:500],
            key_facts=all_content[:3],
        )

    except Exception as e:
        logger.warning("Search failed for %s: %s", company.name, e)
        return CompanyResearch(
            name=company.name,
            booth_context=company.booth_context,
            search_failed=True,
        )


async def _search_leadership(
    client: AsyncTavilyClient, company: CompanyResearch
) -> str:
    """Search for a company's leadership team across LinkedIn, Crunchbase, and general web."""
    query = (
        f"{company.name} CEO CTO CFO COO CPO founder"
        f" leadership team LinkedIn Crunchbase"
    )

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=5,
            include_answer="basic",
        )

        snippets = []
        answer = response.get("answer", "")
        if answer:
            snippets.append(answer)

        for result in response.get("results", []):
            content = result.get("content", "")
            if content:
                snippets.append(content)

        return "\n---\n".join(snippets[:4])[:1500]

    except Exception as e:
        logger.warning("Leadership search failed for %s: %s", company.name, e)
        return ""


async def _search_founder_background(
    client: AsyncTavilyClient, company: CompanyResearch
) -> str:
    """Deep search for founder/CEO biographical details: education, origin, languages."""
    query = (
        f"{company.name} founder CEO origin education university background"
        f" biography born studied"
    )

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=5,
            include_answer="basic",
        )

        snippets = []
        answer = response.get("answer", "")
        if answer:
            snippets.append(answer)

        for result in response.get("results", []):
            content = result.get("content", "")
            if content:
                snippets.append(content)

        return "\n---\n".join(snippets[:4])[:1500]

    except Exception as e:
        logger.warning("Background search failed for %s: %s", company.name, e)
        return ""


async def research_companies(
    config: Config, companies: list[CompanyInfo]
) -> list[CompanyResearch]:
    """Research all companies concurrently via Tavily (company info + leadership + backgrounds)."""
    client = AsyncTavilyClient(api_key=config.tavily_api_key)

    # Phase 1: Company research (concurrent)
    tasks = [_search_one_company(client, company) for company in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    researched = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("Research task failed for %s: %s", companies[i].name, result)
            researched.append(
                CompanyResearch(
                    name=companies[i].name,
                    booth_context=companies[i].booth_context,
                    search_failed=True,
                )
            )
        else:
            researched.append(result)

    # Phase 2: Leadership + founder background research (all concurrent)
    leadership_tasks = [_search_leadership(client, r) for r in researched]
    background_tasks = [_search_founder_background(client, r) for r in researched]
    all_tasks = leadership_tasks + background_tasks
    all_results = await asyncio.gather(*all_tasks, return_exceptions=True)

    n = len(researched)
    leadership_results = all_results[:n]
    background_results = all_results[n:]

    for i in range(n):
        # Leadership
        if isinstance(leadership_results[i], str):
            researched[i].leadership_info = leadership_results[i]
        else:
            logger.warning(
                "Leadership research failed for %s: %s",
                researched[i].name,
                leadership_results[i],
            )
        # Background
        if isinstance(background_results[i], str):
            researched[i].founder_background = background_results[i]
        else:
            logger.warning(
                "Background research failed for %s: %s",
                researched[i].name,
                background_results[i],
            )

    logger.info(
        "Researched %d companies (%d failures)",
        len(researched),
        sum(1 for r in researched if r.search_failed),
    )
    return researched
