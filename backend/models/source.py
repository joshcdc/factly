"""Source: the normalised research record Agent 1 hands to Agent 2 (AGENT.md section 3)."""

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["news", "government", "company", "academic", "reference", "social", "web"]


class Source(BaseModel):
    id: str  # "source_1", "source_2", ... in search-rank order
    url: str
    title: str
    publisher: str  # registrable domain, e.g. "reuters.com"
    published_at: str | None = None  # ISO date when Linkup knows it
    content: str  # cleaned page text (full page when fetched, else the search passage)
    source_type: SourceType = "web"
    credibility_score: int | None = Field(None, ge=1, le=5)  # set by Agent 2's source ranking
    relevance_score: int = Field(3, ge=1, le=5)  # from search rank: 5 = top results
