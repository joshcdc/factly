"""Rule-based source credibility (1-5) from source_type and publisher domain."""

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


MAX_SOURCES = 10  # analysed per investigation; more mostly adds repeats of the same story
MAX_PER_PUBLISHER = 2  # a publisher counts as one voice, so extra pages from it add little


def select_sources(sources: list[Source], limit: int = MAX_SOURCES) -> list[Source]:
    """Best `limit` sources: most relevant first, then most credible, at most 2 per publisher."""
    ranked = sorted(sources, key=lambda s: (-s.relevance_score, -(s.credibility_score or 0)))
    per_pub: dict[str, int] = {}
    out = []
    for s in ranked:
        if per_pub.get(s.publisher, 0) >= MAX_PER_PUBLISHER:
            continue
        per_pub[s.publisher] = per_pub.get(s.publisher, 0) + 1
        out.append(s)
        if len(out) == limit:
            break
    return out
