"""Turn raw Linkup results into contract `Source` records."""

import html
import re
from urllib.parse import urlsplit, urlunsplit

from backend.models.source import Source, SourceType

MAX_CONTENT_CHARS = 20_000

_NEWS = {
    "reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "ft.com", "wsj.com", "nytimes.com", "bloomberg.com",
    "theguardian.com", "cnbc.com", "cnn.com", "washingtonpost.com", "economist.com", "theverge.com",
    "techcrunch.com", "axios.com", "forbes.com", "businessinsider.com", "npr.org", "politico.com", "wired.com",
}
_SOCIAL = {"reddit.com", "x.com", "twitter.com", "facebook.com", "medium.com", "substack.com", "youtube.com",
           "linkedin.com", "quora.com", "tiktok.com", "instagram.com"}
_REFERENCE = {"wikipedia.org", "britannica.com"}
_ACADEMIC = {"arxiv.org", "nature.com", "science.org", "doi.org", "ncbi.nlm.nih.gov", "sciencedirect.com",
             "springer.com", "ssrn.com", "jstor.org"}


def canonical_url(url: str) -> str:
    """For de-duplication: drop fragment, trailing slash and leading www."""
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    return urlunsplit((p.scheme.lower() or "https", host, p.path.rstrip("/"), p.query, ""))


def publisher(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    # keep 3 labels for two-part public suffixes like bbc.co.uk / gov.uk
    if len(parts) >= 3 and parts[-2] in {"co", "com", "gov", "ac", "org", "net", "edu"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def source_type(url: str) -> SourceType:
    p = urlsplit(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.lower()
    labels = host.split(".")
    if {"gov", "mil"} & set(labels) or host.endswith("europa.eu") or labels[-1] == "int":
        return "government"
    if _matches(host, _ACADEMIC) or host.endswith(".edu") or ".ac." in host:
        return "academic"
    if _matches(host, _REFERENCE):
        return "reference"
    if _matches(host, _SOCIAL):
        return "social"
    if _matches(host, _NEWS) or "/news/" in path:
        return "news"
    if host.startswith(("ir.", "investor.", "investors.")) or "/investor" in path or "/press-release" in path:
        return "company"
    return "web"


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"(\*\*|__)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CONTENT_CHARS]


def to_source(raw: dict, rank: int) -> Source:
    """rank is 0-based position across all merged results; drives source id and relevance_score."""
    return Source(
        id=f"source_{rank + 1}",
        url=raw["url"],
        title=clean(raw.get("title") or "")[:300] or publisher(raw["url"]),
        publisher=publisher(raw["url"]),
        published_at=(raw.get("published_at") or None) and str(raw["published_at"])[:10],
        content=clean(raw.get("content", "")),
        source_type=source_type(raw["url"]),
        relevance_score=max(1, 5 - rank // 3),  # 5 for the top 3, 4 for the next 3, ...
    )
