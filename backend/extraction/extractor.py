"""Per-source LLM extraction (entities, relationships, candidate excerpts). No classification here."""

import logging
import re

import anthropic
from dotenv import load_dotenv

from backend.models.source import Source

from . import prompts
from .schemas import EntitySummary, SourceExtraction

load_dotenv()

log = logging.getLogger("fakta.extract")

MODEL = "claude-haiku-5-5"  # extraction is simple; move to claude-sonnet-5-5 if graphs look sloppy
EFFORT = "low"  # extraction, not reasoning: keep it fast
MAX_EXCERPTS = 3
MAX_ENTITIES = 10
MAX_RELATIONSHIPS = 12

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(max_retries=3)
    return _client


async def extract(claim: str, source: Source) -> SourceExtraction:
    resp = await client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=prompts.EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": prompts.EXTRACT_USER.format(
            claim=claim, title=source.title, publisher=source.publisher, content=source.content)}],
        output_format=SourceExtraction,
        output_config={"effort": EFFORT},
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"extraction failed for {source.id}: stop_reason={resp.stop_reason}")
    out = resp.parsed_output
    out.entities = [e for e in out.entities if is_noun_name(e.name)][:MAX_ENTITIES]
    out.excerpts = out.excerpts[:MAX_EXCERPTS]
    for r in out.relationships:
        r.relationship = clean_label(r.relationship)
    out.relationships = [r for r in out.relationships if r.relationship][:MAX_RELATIONSHIPS]
    return out


def is_noun_name(name: str) -> bool:
    """Reject sentences, headlines and opinions posing as entity names."""
    name = name.strip()
    # sentence signs: ?!:;" anywhere, or a lowercase word ending a sentence ("estimates. "), but not "U.S."
    return 0 < len(name.split()) <= 5 and not re.search(r"[?!:;\"]|\b[a-z]{3,}\.(\s|$)", name)


_AUX = re.compile(r"^(?:has|have|had|is|was|are|were|been)\s+")


def clean_label(label: str) -> str:
    """'Has invested in' -> 'invested in'; 'Alleged affair with' keeps its prefix. Labels longer than 4 words
    are dropped ('')."""
    label = _AUX.sub("", label.strip().lower())
    return label if 0 < len(label.split()) <= 4 else ""


async def summarise(claim: str, name: str, type_: str, mentions: list[tuple[str, str]]) -> str | None:
    """One short summary of an entity from what each source said about it. None on any failure: the caller
    keeps the plain description, so a summary problem never fails an investigation."""
    notes = "\n".join(f"- {publisher}: {text}" for publisher, text in mentions if text)
    for attempt in (1, 2):  # one retry: a first call occasionally fails and the same request then succeeds
        try:
            resp = await client().messages.parse(
                model=MODEL,
                max_tokens=2000,  # the model also thinks; 400 truncated long entities mid-sentence
                system=prompts.SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": prompts.SUMMARY_USER.format(
                    claim=claim, name=name, type=type_, notes=notes)}],
                output_format=EntitySummary,
                output_config={"effort": EFFORT},
            )
            if resp.stop_reason == "refusal" or resp.parsed_output is None:
                log.warning("summary for %r: stop_reason=%s, no output (attempt %d)", name, resp.stop_reason, attempt)
                continue
            return resp.parsed_output.summary.strip() or None
        except Exception as e:
            log.warning("summary for %r failed (attempt %d): %s: %s", name, attempt, type(e).__name__, str(e)[:200])
    return None
