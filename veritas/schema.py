"""Pydantic models: the public report schema plus the LLM output schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["factual", "prediction", "opinion"]
Verdict = Literal["supported", "contradicted", "misleading", "insufficient", "not_verifiable"]
Stance = Literal["supports", "contradicts", "context"]
VERDICTS: tuple[str, ...] = Verdict.__args__  # type: ignore[attr-defined]


# ---------------------------------------------------------------- public report


class Evidence(BaseModel):
    url: str
    title: str
    quote: str
    stance: Stance
    quote_verified: bool = False


class Step(BaseModel):
    query: str
    finding: str
    next_action: str


class Claim(BaseModel):
    text: str
    kind: Kind
    verdict: Verdict | None = None
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    trace: list[Step] = Field(default_factory=list)


class Report(BaseModel):
    input_text: str
    pub_date: str | None = None
    claims: list[Claim] = Field(default_factory=list)


# ---------------------------------------------------------------- LLM outputs


class ExtractedClaim(BaseModel):
    text: str = Field(description="Atomic, self-contained claim; pronouns and relative dates resolved")
    kind: Kind


class Extraction(BaseModel):
    claims: list[ExtractedClaim]


class QueryPlan(BaseModel):
    query: str


class EvidenceDraft(BaseModel):
    source_index: int = Field(description="Index [n] of the source the quote is copied from")
    quote: str = Field(description="Copied verbatim from that source's text")
    stance: Stance


class Judgement(BaseModel):
    sufficient: bool
    verdict: Verdict
    explanation: str
    evidence: list[EvidenceDraft]
    missing_info: str
    next_query: str
