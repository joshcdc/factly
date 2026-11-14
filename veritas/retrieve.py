"""Web retrieval via Linkup + quote verification.

Linkup SDK facts (checked against installed linkup-sdk 0.24.1):
  LinkupClient(api_key=None)  # falls back to LINKUP_API_KEY env var
  client.search(query, *, depth: 'flash'|'fast'|'standard'|'deep',
                output_type: 'searchResults'|'sourcedAnswer'|'structured',
                max_results=None, from_date=None, to_date=None, ...)
  -> LinkupSearchResults(results=[LinkupSearchTextResult(type='text', name, url, content,
                                                         favicon, published_at) | LinkupSearchImageResult])
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

FUZZY_THRESHOLD = 0.9
MIN_QUOTE_WORDS = 4  # a quote shorter than this proves nothing
MAX_RESULTS = 6


@lru_cache(maxsize=1)
def _client():
    from linkup import LinkupClient

    key = os.getenv("LINKUP_API_KEY")
    if not key:
        raise RuntimeError("LINKUP_API_KEY is not set (copy .env.example to .env)")
    return LinkupClient(api_key=key)


def search(query: str, depth: str = "standard", max_results: int = MAX_RESULTS) -> list[dict]:
    """Return raw passages: [{title, url, content, published_at}]. Never uses sourcedAnswer."""
    resp = _client().search(
        query=query,
        depth=depth,
        output_type="searchResults",
        max_results=max_results,
    )
    out = []
    for r in resp.results:
        if getattr(r, "type", None) != "text" or not r.content:
            continue
        out.append(
            {
                "title": r.name,
                "url": r.url,
                "content": r.content,
                "published_at": str(r.published_at) if getattr(r, "published_at", None) else None,
            }
        )
    return out


# ---------------------------------------------------------------- quote verification

_TRANSLATE = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-", "−": "-",
        " ": " ",
    }
)


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_TRANSLATE).lower()
    return re.sub(r"\s+", " ", s).strip()


def _fuzzy_contains(q: str, src: str, threshold: float) -> bool:
    """Is there a window in src of ~len(q) chars whose similarity to q is >= threshold?"""
    n = len(q)
    if n == 0 or len(src) < n * 0.8:
        return False
    # Anchor candidate windows on long matching blocks instead of sliding over every offset.
    sm = SequenceMatcher(None, src, q, autojunk=False)
    starts = set()
    for a, b, size in sm.get_matching_blocks():
        if size >= min(12, n // 4) and size > 0:
            starts.add(max(0, a - b))
    for st in starts:
        for delta in (-3, 0, 3):
            s0 = max(0, st + delta)
            for length in (n, int(n * 1.05), int(n * 0.95)):
                window = src[s0 : s0 + length]
                if SequenceMatcher(None, window, q, autojunk=False).ratio() >= threshold:
                    # Fuzzy tolerance is for typos/punctuation, never for numbers:
                    # every number in the quote must appear exactly in the matched region.
                    region = src[max(0, s0 - 10) : s0 + length + 10]
                    if set(_NUM.findall(q)) <= set(_NUM.findall(region)):
                        return True
    return False


_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def verify_quote(quote: str, source_text: str, threshold: float = FUZZY_THRESHOLD) -> bool:
    """True iff the quote appears (near-)verbatim in source_text.

    Ellipses split the quote into fragments; every fragment must verify on its own.
    """
    if not quote or not source_text:
        return False
    src = normalise(source_text)
    fragments = [normalise(f).strip(" \"'") for f in re.split(r"\.\.\.|…|\[\.\.\.\]", quote)]
    fragments = [f for f in fragments if f]
    if not fragments or sum(len(f.split()) for f in fragments) < MIN_QUOTE_WORDS:
        return False
    for frag in fragments:
        if frag in src:
            continue
        if not _fuzzy_contains(frag, src, threshold):
            return False
    return True


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Tesla total revenue 2024 annual report"
    results = search(q)
    print(f"{len(results)} results for: {q}\n")
    for r in results:
        print(f"- {r['title']}\n  {r['url']}\n  {r['content'][:300].replace(chr(10), ' ')}...\n")
