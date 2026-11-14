"""Gather sources for a topic or claim: a few searches in parallel, de-duplicated, full pages where useful."""

from concurrent.futures import ThreadPoolExecutor

from backend.models.source import Source
from backend.research import linkup
from backend.research.normalise import canonical_url, to_source

MAX_SOURCES = 12
RESULTS_PER_QUERY = 8
FETCH_IF_SHORTER_THAN = 1500  # chars: search passage too thin, fetch the full page
MAX_FETCHES = 6


def queries_for(query: str, mode: str) -> list[str]:
    q = query.strip()
    if mode == "claim":
        # one neutral search plus angles that surface both supporting and contradicting sources
        return [q, f"fact check: {q}", f"{q} official statement"]
    return [q, f"{q} official announcement", f"{q} latest news"]


def gather(query: str, mode: str) -> list[Source]:
    qs = queries_for(query, mode)
    with ThreadPoolExecutor(max_workers=len(qs)) as pool:
        futures = [pool.submit(linkup.search, q, "standard", RESULTS_PER_QUERY) for q in qs]
        batches, errors = [], []
        for f in futures:
            try:
                batches.append(f.result())
            except linkup.ResearchError as e:
                errors.append(e)
    if not batches:  # every search failed: surface the first reason (credits, key, timeout...)
        raise errors[0]

    # Interleave batches so each query's best results come first, then de-duplicate by URL.
    merged, seen = [], set()
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

    mode = "claim" if "--claim" in sys.argv else "topic"
    q = " ".join(a for a in sys.argv[1:] if a != "--claim") or "Relationship between OpenAI and Microsoft"
    for s in gather(q, mode):
        print(f"{s.id:10} {s.relevance_score} {s.source_type:10} {s.publisher:22} {len(s.content):6} chars  {s.title[:60]}")
