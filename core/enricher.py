"""Tavily-based enrichment for exhibitors missing descriptions.

Only enriches exhibitors that lack a description after scraping.
Searches for company info + leadership data concurrently.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from tavily import AsyncTavilyClient

from core.config import Config
from core.db import ExhibitorRow

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Enrichment data from web search."""
    exhibitor_id: int
    description: str = ""
    website_url: str = ""
    key_facts: list[str] = field(default_factory=list)
    leadership_info: str = ""
    founder_background: str = ""
    search_failed: bool = False


async def _search_company(
    client: AsyncTavilyClient, exhibitor: ExhibitorRow
) -> EnrichmentResult:
    """Search for a single company's info via Tavily."""
    query = f"{exhibitor.company_name} company employees headcount funding"
    if exhibitor.categories:
        query += f" {' '.join(exhibitor.categories[:2])}"

    try:
        response = await client.search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=5,
            include_answer="basic",
        )

        website = exhibitor.website_url
        all_content = []

        for result in response.get("results", []):
            url = result.get("url", "")
            name_lower = exhibitor.company_name.lower().replace(" ", "")
            if name_lower in url.lower() and not website:
                website = url
            content = result.get("content", "")
            if content:
                all_content.append(content)

        answer = response.get("answer", "")
        description = answer if answer else (all_content[0] if all_content else "")

        return EnrichmentResult(
            exhibitor_id=exhibitor.id,
            description=description[:500],
            website_url=website,
            key_facts=all_content[:3],
        )

    except Exception as e:
        logger.warning("Search failed for %s: %s", exhibitor.company_name, e)
        return EnrichmentResult(
            exhibitor_id=exhibitor.id, search_failed=True
        )


async def _search_leadership(
    client: AsyncTavilyClient, exhibitor: ExhibitorRow
) -> str:
    """Search for company leadership team."""
    query = (
        f"{exhibitor.company_name} CEO CTO CFO COO CPO founder"
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
        logger.warning("Leadership search failed for %s: %s",
                       exhibitor.company_name, e)
        return ""


async def _search_founder_background(
    client: AsyncTavilyClient, exhibitor: ExhibitorRow
) -> str:
    """Search for founder/CEO biographical details."""
    query = (
        f"{exhibitor.company_name} founder CEO origin education university"
        f" background biography born studied"
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
        logger.warning("Background search failed for %s: %s",
                       exhibitor.company_name, e)
        return ""


async def enrich_exhibitors(
    config: Config,
    exhibitors: list[ExhibitorRow],
    on_progress=None,
) -> list[EnrichmentResult]:
    """Enrich exhibitors with Tavily web search.

    Runs three concurrent search phases:
    1. Company info (description, website, key facts)
    2. Leadership team
    3. Founder background
    """
    if not exhibitors:
        return []

    client = AsyncTavilyClient(api_key=config.tavily_api_key)
    total = len(exhibitors)

    # Phase 1: Company research (concurrent, batched to avoid rate limits)
    batch_size = 10
    results = []

    for i in range(0, total, batch_size):
        batch = exhibitors[i : i + batch_size]
        tasks = [_search_company(client, e) for e in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error("Enrichment failed for %s: %s",
                             batch[j].company_name, result)
                results.append(EnrichmentResult(
                    exhibitor_id=batch[j].id, search_failed=True
                ))
            else:
                results.append(result)

        if on_progress:
            await on_progress(
                "enrich",
                f"Researched {min(i + batch_size, total)}/{total} companies...",
                min(i + batch_size, total),
                total,
            )

        if i + batch_size < total:
            await asyncio.sleep(1.0)  # Rate limit pause between batches

    # Phase 2: Leadership + founder background (concurrent)
    if on_progress:
        await on_progress("enrich", "Researching leadership teams...", 0, total)

    leadership_tasks = [_search_leadership(client, e) for e in exhibitors]
    background_tasks = [_search_founder_background(client, e) for e in exhibitors]
    all_extra = await asyncio.gather(
        *(leadership_tasks + background_tasks), return_exceptions=True
    )

    n = len(exhibitors)
    for i in range(n):
        # Leadership
        leadership_result = all_extra[i]
        if isinstance(leadership_result, str):
            results[i].leadership_info = leadership_result

        # Background
        background_result = all_extra[n + i]
        if isinstance(background_result, str):
            results[i].founder_background = background_result

    if on_progress:
        await on_progress(
            "enrich",
            f"Enrichment complete for {total} companies",
            total,
            total,
        )

    logger.info(
        "Enriched %d exhibitors (%d failures)",
        len(results),
        sum(1 for r in results if r.search_failed),
    )
    return results
