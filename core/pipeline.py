"""Full pipeline orchestrator: scrape → store → enrich → score → return results.

Supports progress callbacks for real-time updates via SSE (web) or
message editing (Telegram).
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from urllib.parse import urlparse

from core.config import Config
from core.db import DB, ScoredExhibitorRow
from core.scraper import ConferenceScraper
from core.enricher import enrich_exhibitors
from core.scorer import score_all_exhibitors

logger = logging.getLogger(__name__)

# Progress callback: (stage, message, current, total)
ProgressCallback = Callable[[str, str, int, int], Awaitable[None]]


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    conference_id: int = 0
    conference_name: str = ""
    scoring_run_id: int = 0
    total_exhibitors: int = 0
    total_scored: int = 0
    results: list[ScoredExhibitorRow] = field(default_factory=list)
    error: str = ""


async def _noop_progress(stage: str, msg: str, current: int, total: int) -> None:
    pass


def _guess_conference_name(url: str) -> str:
    """Guess a conference name from the URL."""
    domain = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    known = {
        "mwcbarcelona": "MWC Barcelona",
        "websummit": "Web Summit",
        "gdconf": "GDC",
        "saastrannual": "SaaStr Annual",
        "token2049": "TOKEN2049",
        "leapsa": "LEAP",
        "leap.sa": "LEAP",
        "ces": "CES",
        "computex": "COMPUTEX",
        "collision": "Collision",
        "techcrunch": "TechCrunch Disrupt",
        "vivatech": "VivaTech",
        "slush": "Slush",
        "gitex": "GITEX",
        "dmexco": "DMEXCO",
        "money2020": "Money20/20",
        "sibos": "Sibos",
        "finovate": "Finovate",
        "hannover": "Hannover Messe",
        "iot-world": "IoT World",
        "rsa": "RSA Conference",
        "blackhat": "Black Hat",
        "awsreinvent": "AWS re:Invent",
        "dreamforce": "Dreamforce",
    }

    for key, name in known.items():
        if key in domain or key in path:
            return name

    # Use domain name cleaned up
    parts = domain.replace("www.", "").split(".")
    return parts[0].title() if parts else "Conference"


async def run_pipeline(
    config: Config,
    url: str,
    icp: str,
    conference_name: str = "",
    force_rescrape: bool = False,
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the full scrape → enrich → score pipeline.

    Args:
        config: App configuration
        url: Conference exhibitor list URL
        icp: User's Ideal Customer Profile text
        conference_name: Optional name override (auto-detected if empty)
        force_rescrape: If True, re-scrape even if conference exists in DB
        on_progress: Async callback for real-time progress updates

    Returns:
        PipelineResult with scored exhibitors
    """
    progress = on_progress or _noop_progress
    result = PipelineResult()

    try:
        # Initialize database
        db = DB(config.db_path)
        await db.init()

        # Determine conference name
        if not conference_name:
            conference_name = _guess_conference_name(url)
        result.conference_name = conference_name

        # Check if already scraped
        existing = await db.get_conference_by_url(url)
        need_scrape = True

        if existing and not force_rescrape:
            result.conference_id = existing["id"]
            count = await db.get_exhibitor_count(existing["id"])
            if count > 0:
                need_scrape = False
                result.total_exhibitors = count
                await progress(
                    "scrape_list",
                    f"Found {count} exhibitors already scraped for {conference_name}. "
                    "Skipping to scoring.",
                    count, count,
                )

        # ── Step 1: Scrape ───────────────────────────────────────
        if need_scrape:
            await progress("scrape_list", f"Starting scrape of {conference_name}...", 0, 0)

            scraper = ConferenceScraper(
                delay=config.scrape_delay,
                max_detail_pages=config.max_detail_pages,
                on_progress=progress,
            )
            scraped = await scraper.scrape(url)

            if not scraped:
                result.error = (
                    "No exhibitors found on this page. "
                    "The page may require login, use CAPTCHAs, "
                    "or have a non-standard layout."
                )
                await progress("error", result.error, 0, 0)
                return result

            # Store in database
            await progress("store", f"Saving {len(scraped)} exhibitors to database...", 0, len(scraped))
            conference_id = await db.upsert_conference(conference_name, url)
            result.conference_id = conference_id

            for i, ex in enumerate(scraped):
                exhibitor_id = await db.upsert_exhibitor(
                    conference_id=conference_id,
                    company_name=ex.company_name,
                    detail_page_url=ex.detail_page_url,
                    booth_location=ex.booth_location,
                    categories=ex.categories,
                )
                # Update detail page data if available
                if any([ex.website_url, ex.linkedin_url, ex.contact_url,
                        ex.description, ex.logo_url]):
                    await db.update_exhibitor_details(
                        exhibitor_id=exhibitor_id,
                        website_url=ex.website_url,
                        linkedin_url=ex.linkedin_url,
                        contact_url=ex.contact_url,
                        description=ex.description,
                        logo_url=ex.logo_url,
                    )

            await db.update_conference_count(conference_id, len(scraped))
            result.total_exhibitors = len(scraped)
            await progress("store", f"Saved {len(scraped)} exhibitors", len(scraped), len(scraped))

        # ── Step 2: Enrich ───────────────────────────────────────
        await progress("enrich", "Checking which exhibitors need enrichment...", 0, 0)
        unenriched = await db.get_exhibitors(
            result.conference_id, only_unenriched=True
        )

        if unenriched:
            await progress(
                "enrich",
                f"Enriching {len(unenriched)} exhibitors via web search...",
                0, len(unenriched),
            )

            enrichment_results = await enrich_exhibitors(
                config, unenriched, on_progress=progress,
            )

            # Store enrichment data
            for er in enrichment_results:
                enrichment_dict = {
                    "description": er.description,
                    "key_facts": er.key_facts,
                    "leadership_info": er.leadership_info,
                    "founder_background": er.founder_background,
                    "search_failed": er.search_failed,
                }
                await db.update_exhibitor_enrichment(
                    er.exhibitor_id, enrichment_dict
                )
                # Also update description if missing
                if er.description:
                    await db.update_exhibitor_details(
                        exhibitor_id=er.exhibitor_id,
                        description=er.description,
                        website_url=er.website_url,
                    )
        else:
            await progress("enrich", "All exhibitors already enriched", 0, 0)

        # ── Step 3: Score ────────────────────────────────────────
        await progress("score", "Starting ICP scoring...", 0, result.total_exhibitors)

        scoring_run_id = await score_all_exhibitors(
            config=config,
            db=db,
            conference_id=result.conference_id,
            icp=icp,
            on_progress=progress,
        )

        result.scoring_run_id = scoring_run_id

        # ── Step 4: Fetch results ────────────────────────────────
        if scoring_run_id:
            results = await db.get_scored_results(scoring_run_id, limit=50)
            result.results = results
            result.total_scored = len(results)

        await progress(
            "complete",
            f"Done! Top {len(result.results)} exhibitors scored.",
            len(result.results),
            len(result.results),
        )

        return result

    except Exception as e:
        logger.exception("Pipeline failed")
        result.error = f"Pipeline error: {type(e).__name__}: {str(e)}"
        await progress("error", result.error, 0, 0)
        return result
