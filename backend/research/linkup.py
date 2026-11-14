"""Thin Linkup wrapper (checked against linkup-sdk 0.24.1).

  client.search(query, *, depth, output_type="searchResults", max_results) -> .results[{type, name, url, content, published_at}]
  client.fetch(url, timeout=...) -> .markdown
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class ResearchError(RuntimeError):
    """A Linkup failure with a message fit to show the user."""


@lru_cache(maxsize=1)
def _client():
    from linkup import LinkupClient

    key = os.getenv("LINKUP_API_KEY")
    if not key:
        raise ResearchError("LINKUP_API_KEY is not set on the server (add it to .env).")
    return LinkupClient(api_key=key)


def _explain(e: Exception) -> ResearchError:
    name = type(e).__name__
    if "InsufficientCredit" in name:
        return ResearchError("Linkup account is out of credits.")
    if "Authentication" in name or "Unauthorized" in name:
        return ResearchError("Linkup API key was rejected.")
    if "Timeout" in name:
        return ResearchError("Linkup search timed out.")
    return ResearchError(f"Linkup search failed: {name}: {e}")


def search(query: str, depth: str = "standard", max_results: int = 8, timeout: float = 45) -> list[dict]:
    """Raw passages: [{title, url, content, published_at}]. Never uses sourcedAnswer."""
    try:
        resp = _client().search(
            query=query, depth=depth, output_type="searchResults", max_results=max_results, timeout=timeout
        )
    except ResearchError:
        raise
    except Exception as e:
        raise _explain(e) from e
    return [
        {
            "title": r.name,
            "url": r.url,
            "content": r.content,
            "published_at": str(r.published_at) if getattr(r, "published_at", None) else None,
        }
        for r in resp.results
        if getattr(r, "type", None) == "text" and r.content
    ]


def fetch(url: str, timeout: float = 20) -> str | None:
    """Full page as markdown, or None if it can't be fetched (callers fall back to the search passage)."""
    try:
        return _client().fetch(url, timeout=timeout).markdown or None
    except Exception:
        return None
