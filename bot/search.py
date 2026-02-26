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
    search_failed: bool = False


async def _search_one_company(
    client: AsyncTavilyClient, company: CompanyInfo
) -> CompanyResearch:
    """Search for a single company and extract structured info."""
    query = f"{company.name} company"
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


async def research_companies(
    config: Config, companies: list[CompanyInfo]
) -> list[CompanyResearch]:
    """Research all companies concurrently via Tavily."""
    client = AsyncTavilyClient(api_key=config.tavily_api_key)

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

    logger.info(
        "Researched %d companies (%d failures)",
        len(researched),
        sum(1 for r in researched if r.search_failed),
    )
    return researched
