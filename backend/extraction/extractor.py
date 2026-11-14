"""Per-source LLM extraction (entities, relationships, candidate excerpts). No classification here."""

import anthropic
from dotenv import load_dotenv

from backend.models.source import Source

from . import prompts
from .schemas import SourceExtraction

load_dotenv()

MODEL = "claude-opus-5-5"
EFFORT = "low"  # extraction, not reasoning: keep it fast
MAX_EXCERPTS = 3

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(max_retries=3)
    return _client


async def extract(claim: str, source: Source) -> SourceExtraction:
    resp = await client().beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=prompts.EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": prompts.EXTRACT_USER.format(
            claim=claim, title=source.title, publisher=source.publisher, content=source.content)}],
        output_format=SourceExtraction,
        output_config={"effort": EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # on a safety refusal, the API retries on a fallback model in the same call
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"extraction failed for {source.id}: stop_reason={resp.stop_reason}")
    out = resp.parsed_output
    out.excerpts = out.excerpts[:MAX_EXCERPTS]
    return out
