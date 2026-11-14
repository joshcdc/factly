"""Gather sources for a topic or claim: a few searches in parallel, de-duplicated, full pages where useful."""

from concurrent.futures import ThreadPoolExecutor

from backend.models.source import Source
from backend.research import linkup
from backend.research.normalise import canonical_url, to_source

MAX_SOURCES = 12
RESULTS_PER_QUERY = 8
FETCH_IF_SHORTER_THAN = 1500  # chars: search passage too thin, fetch the full page
MAX_FETCHES = 6
MAX_AUTHORITATIVE = 6  # slots reserved for the trusted-domain search, ahead of the open web

# Regulators, statistics offices, filings, wires, major newsrooms and press-release services (which carry
# companies' own announcements). Searched separately so they aren't crowded out by blogs and aggregators.
AUTHORITATIVE_DOMAINS = [
    "sec.gov", "ftc.gov", "justice.gov", "federalreserve.gov", "bls.gov", "bea.gov", "census.gov", "cdc.gov",
    "nih.gov", "gov.uk", "ons.gov.uk", "europa.eu", "who.int", "imf.org", "worldbank.org", "oecd.org",
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com", "nytimes.com", "washingtonpost.com",
    "bbc.co.uk", "bbc.com", "theguardian.com", "economist.com", "cnbc.com", "npr.org", "axios.com",
    "techcrunch.com", "theverge.com", "nature.com", "science.org",
    "prnewswire.com", "businesswire.com", "globenewswire.com",
]


def queries_for(claim: str) -> list[str]:
    q = claim.strip()
    # one neutral search plus angles that surface both supporting and contradicting sources
    return [q, f"fact check: {q}", f"{q} official statement"]


def gather(claim: str) -> list[Source]:
    qs = queries_for(claim)
    with ThreadPoolExecutor(max_workers=len(qs) + 1) as pool:
        trusted = pool.submit(linkup.search, claim.strip(), "standard", RESULTS_PER_QUERY,
                              include_domains=AUTHORITATIVE_DOMAINS)
        futures = [pool.submit(linkup.search, q, "standard", RESULTS_PER_QUERY) for q in qs]
        batches, errors = [], []
        for f in futures:
            try:
                batches.append(f.result())
            except linkup.ResearchError as e:
                errors.append(e)
        try:
            top = trusted.result()[:MAX_AUTHORITATIVE]
        except linkup.ResearchError as e:
            top, errors = [], errors + [e]
    if not batches and not top:  # every search failed: surface the first reason (credits, key, timeout...)
        raise errors[0]

    # Trusted-domain hits first, then interleave the open-web batches; de-duplicate by URL throughout.
    merged, seen = [], set()
    for r in top:
        key = canonical_url(r["url"])
        if key not in seen:
            seen.add(key)
            merged.append(r)
    for i in range(max(map(len, batches), default=0)):
        for batch in batches:
            if i < len(batch):
                key = canonical_url(batch[i]["url"])
                if key not in seen:
                    seen.add(key)
                    merged.append(batch[i])
    merged = merged[:MAX_SOURCES]

    # Search passages can be thin; fetch the full page for the top few short ones.
    thin = [r for r in merged if len(r["content"]) < FETCH_IF_SHORTER_THAN][:MAX_FETCHES]
    if thin:
        with ThreadPoolExecutor(max_workers=len(thin)) as pool:
            for r, page in zip(thin, pool.map(lambda r: linkup.fetch(r["url"]), thin)):
                if page and len(page) > len(r["content"]):
                    r["content"] = page

    return [to_source(r, rank) for rank, r in enumerate(merged)]


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Microsoft controls OpenAI"
    for s in gather(q):
        print(f"{s.id:10} {s.relevance_score} {s.source_type:10} {s.publisher:22} {len(s.content):6} chars  {s.title[:60]}")
