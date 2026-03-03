"""Telegram MarkdownV2 message formatting."""

import re

from bot.matcher import ScoredCompany
from core.db import ScoredExhibitorRow


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


def _score_emoji(score: int) -> str:
    if score >= 8:
        return "\U0001f7e2"   # green
    elif score >= 5:
        return "\U0001f7e1"   # yellow
    elif score >= 1:
        return "\U0001f534"   # red
    return "\u26aa"           # white


def format_results(scored_companies: list[ScoredCompany]) -> str:
    """Format scored companies for Telegram (photo pipeline)."""
    if not scored_companies:
        return _escape_md("No companies found to analyze.")

    lines = ["*" + _escape_md("Booth Analysis Results") + "*", ""]

    for i, company in enumerate(scored_companies, 1):
        emoji = _score_emoji(company.score)
        name_esc = _escape_md(company.name)
        score_esc = _escape_md(f"{company.score}/10")

        lines.append(f"*{_escape_md(str(i))}\\. {name_esc}* {emoji} {score_esc}")

        if company.summary:
            lines.append(_escape_md(company.summary))
        if company.match_reason:
            lines.append(f"_{_escape_md(company.match_reason)}_")
        if company.russian_speaking_leaders:
            lines.append(
                "\U0001f1f7\U0001f1fa "
                + _escape_md(company.russian_speaking_leaders)
            )
        if company.website:
            url_escaped = company.website.replace(")", "\\)")
            lines.append(f"[Website]({url_escaped})")
        if company.search_failed:
            lines.append(_escape_md("(Research unavailable)"))
        lines.append("")

    return "\n".join(lines)


def format_scan_results(results: list[ScoredExhibitorRow]) -> str:
    """Format scored exhibitors for Telegram (conference scan pipeline)."""
    if not results:
        return _escape_md("No exhibitors found.")

    lines = ["*" + _escape_md("Conference Exhibitor Scan Results") + "*", ""]

    for i, r in enumerate(results[:30], 1):  # Cap at 30 for Telegram message size
        emoji = _score_emoji(r.score)
        name_esc = _escape_md(r.company_name)
        score_esc = _escape_md(f"{r.score}/10")

        lines.append(f"*{_escape_md(str(i))}\\. {name_esc}* {emoji} {score_esc}")

        if r.summary:
            lines.append(_escape_md(r.summary))
        if r.reasoning:
            lines.append(f"_{_escape_md(r.reasoning)}_")
        if r.russian_speaking_leaders:
            lines.append(
                "\U0001f1f7\U0001f1fa "
                + _escape_md(r.russian_speaking_leaders)
            )

        link_parts = []
        if r.website_url:
            url_esc = r.website_url.replace(")", "\\)")
            link_parts.append(f"[Web]({url_esc})")
        if r.linkedin_url:
            url_esc = r.linkedin_url.replace(")", "\\)")
            link_parts.append(f"[LinkedIn]({url_esc})")
        if link_parts:
            lines.append(" \\| ".join(link_parts))

        lines.append("")

    if len(results) > 30:
        lines.append(
            _escape_md(f"... and {len(results) - 30} more. "
                       "Use the web app for full results.")
        )

    return "\n".join(lines)


def format_no_icp_warning() -> str:
    return (
        "You haven't set your Ideal Customer Profile yet.\n"
        "Use /seticp to define it first.\n\n"
        "Example: /seticp B2B SaaS, 50-500 employees, Series A+, "
        "US-based, needs data infrastructure"
    )


def format_error(error: Exception) -> str:
    error_str = str(error).lower()
    if "rate" in error_str or "429" in error_str:
        return "Rate limit hit. Please wait a moment and try again."
    if "timeout" in error_str:
        return "Request timed out. Please try again."
    return f"Something went wrong during analysis. ({type(error).__name__})"
