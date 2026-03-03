"""LLM-based data extraction from HTML pages.

Used as a fallback when DOM-based scraping doesn't find structured patterns.
Sends page text + links to Claude Haiku for structured extraction.
"""

import json
import logging
from dataclasses import dataclass

import anthropic

from core.config import Config

logger = logging.getLogger(__name__)

LIST_EXTRACTION_PROMPT = """\
You are extracting exhibitor/company names from a conference website page.

Below is the text content of a conference exhibitor list page, plus all links found on the page.

## Page text:
{page_text}

## Links found on page (format: "text -> url"):
{links_text}

## Instructions:
Extract every company/exhibitor name you can find. For each one, also find:
- detail_page_url: a link to their individual profile/detail page on this conference site (if any)
- booth_location: their booth/stand number (if visible)
- categories: any sector/category tags

Return a JSON array. Example:
[
  {{"company_name": "Acme Corp", "detail_page_url": "https://conf.com/exhibitors/acme", "booth_location": "H3.B42", "categories": ["AI", "SaaS"]}},
  {{"company_name": "Beta Inc", "detail_page_url": "", "booth_location": "", "categories": []}}
]

Rules:
- Only include actual company/exhibitor names, not navigation items or page UI elements
- If unsure whether something is a company name, include it
- Return ONLY the JSON array, nothing else
- If you find NO exhibitors, return an empty array: []
"""

DETAIL_EXTRACTION_PROMPT = """\
You are extracting company information from a conference exhibitor's detail page.

## Page text:
{page_text}

## Links found on page (format: "text -> url"):
{links_text}

## Instructions:
Extract the following information about this company:
- website_url: the company's own website (NOT the conference site, NOT social media)
- linkedin_url: their LinkedIn company page URL
- contact_url: contact page URL or email (mailto: link)
- description: a brief description of what the company does (max 2 sentences)
- categories: sector/industry tags
- booth_location: booth/stand number

Return a single JSON object. Example:
{{"website_url": "https://acme.com", "linkedin_url": "https://linkedin.com/company/acme", \
"contact_url": "mailto:info@acme.com", "description": "Cloud infrastructure platform for AI workloads.", \
"categories": ["Cloud", "AI"], "booth_location": "H3.B42"}}

Rules:
- website_url should be the company's OWN domain, not the conference site
- Only include URLs you actually find, use empty string "" for missing fields
- Keep description concise — 1-2 sentences max
- Return ONLY the JSON object, nothing else
"""


async def extract_exhibitors_from_text(
    config: Config,
    page_text: str,
    links: list[tuple[str, str]],
) -> list[dict]:
    """Use Claude Haiku to extract exhibitor names from page text.

    Args:
        config: App configuration
        page_text: The visible text content of the page
        links: List of (text, url) tuples for all links on the page

    Returns:
        List of dicts with keys: company_name, detail_page_url, booth_location, categories
    """
    # Truncate to fit context window
    page_text = page_text[:15000]
    links_text = "\n".join(
        f"{text} -> {url}" for text, url in links[:500]
    )
    links_text = links_text[:10000]

    prompt = LIST_EXTRACTION_PROMPT.format(
        page_text=page_text,
        links_text=links_text,
    )

    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    try:
        message = await client.messages.create(
            model=config.claude_model_extract,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        if isinstance(data, list):
            logger.info("LLM extracted %d exhibitors from page text", len(data))
            return data
        return []

    except Exception as e:
        logger.error("LLM extraction failed: %s", e)
        return []


async def extract_detail_from_text(
    config: Config,
    page_text: str,
    links: list[tuple[str, str]],
) -> dict:
    """Use Claude Haiku to extract company details from a detail page.

    Returns:
        Dict with keys: website_url, linkedin_url, contact_url, description, categories, booth_location
    """
    page_text = page_text[:10000]
    links_text = "\n".join(
        f"{text} -> {url}" for text, url in links[:200]
    )
    links_text = links_text[:5000]

    prompt = DETAIL_EXTRACTION_PROMPT.format(
        page_text=page_text,
        links_text=links_text,
    )

    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    try:
        message = await client.messages.create(
            model=config.claude_model_extract,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}

    except Exception as e:
        logger.error("LLM detail extraction failed: %s", e)
        return {}
