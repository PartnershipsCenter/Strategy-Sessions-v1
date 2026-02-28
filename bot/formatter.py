import re

from bot.matcher import ScoredCompany


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)


def _score_emoji(score: int) -> str:
    if score >= 8:
        return "\U0001f7e2"  # green circle
    elif score >= 5:
        return "\U0001f7e1"  # yellow circle
    elif score >= 1:
        return "\U0001f534"  # red circle
    return "\u26aa"  # white circle


def format_results(scored_companies: list[ScoredCompany]) -> str:
    """Format scored companies into a Telegram MarkdownV2 message."""
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
                "\U0001f1f7\U0001f1fa "  # Russian flag emoji
                + _escape_md(company.russian_speaking_leaders)
            )

        if company.website:
            url_escaped = company.website.replace(")", "\\)")
            lines.append(f"[Website]({url_escaped})")

        if company.search_failed:
            lines.append(_escape_md("(Research unavailable)"))

        lines.append("")

    return "\n".join(lines)


def format_no_icp_warning() -> str:
    return (
        "You haven't set your Ideal Customer Profile yet.\n"
        "Use /seticp to define it first.\n\n"
        "Example: /seticp B2B SaaS, 50-500 employees, Series A+, "
        "US-based, needs data infrastructure"
    )


def format_error(error: Exception) -> str:
    """User-friendly error message."""
    error_str = str(error).lower()
    if "rate" in error_str or "429" in error_str:
        return "Rate limit hit. Please wait a moment and try again."
    if "timeout" in error_str:
        return "Request timed out. Please try again."
    return f"Something went wrong during analysis. ({type(error).__name__})"
