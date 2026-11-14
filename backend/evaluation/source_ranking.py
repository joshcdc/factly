"""Source credibility (1-5): Jev rates each source; rule-based scores from source_type and domain are the fallback."""

from backend.evaluation import jev
from backend.models.source import Source

BY_TYPE = {"government": 5, "academic": 5, "news": 3, "company": 3, "reference": 3, "web": 2, "social": 1}
TOP_NEWS = {"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "wsj.com", "nytimes.com",
            "bloomberg.com", "theguardian.com", "economist.com", "nature.com", "science.org"}


def credibility(source: Source) -> int:
    domain = source.publisher.lower().removeprefix("www.")
    if domain in TOP_NEWS:
        return 4
    if domain.endswith((".gov", ".edu")) or ".gov." in domain or ".ac." in domain:
        return 5
    return BY_TYPE.get(source.source_type, 2)


def rank(sources: list[Source]) -> None:
    """Set credibility_score in place."""
    for s in sources:
        s.credibility_score = credibility(s)


async def rank_async(claim: str, sources: list[Source]) -> None:
    """Set credibility_score in place: Jev's rating where available, else the rule-based score."""
    rank(sources)
    for s, score in zip(sources, await jev.rate_credibility(claim, sources)):
        if score is not None:
            s.credibility_score = score
