"""Stage 2: the agent loop. Search -> judge -> (search again) -> verdict with verified evidence."""

from __future__ import annotations

from . import prompts
from .extract import effective_date
from .llm import call_json
from .retrieve import normalise, search, verify_quote
from .schema import Claim, Evidence, Judgement, QueryPlan, Step

MAX_SEARCHES = 3
SOURCE_CHARS = 5000  # per-source text shown to the judge
DECISIVE = {"supported", "contradicted", "misleading"}


def _format_sources(sources: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sources):
        date = f" (published {s['published_at']})" if s.get("published_at") else ""
        parts.append(f"[{i}] {s['title']}{date}\nURL: {s['url']}\n{s['content'][:SOURCE_CHARS]}")
    return "\n\n---\n\n".join(parts) or "(no sources)"


def _format_history(trace: list[Step]) -> str:
    if not trace:
        return "(none)"
    return "\n".join(f"{i + 1}. query={s.query!r} -> {s.finding}" for i, s in enumerate(trace))


def _verified_evidence(j: Judgement, sources: list[dict]) -> tuple[list[Evidence], int]:
    """Keep only quotes that verifiably appear in the cited source. Returns (kept, n_dropped)."""
    kept, seen, dropped = [], set(), 0
    for d in j.evidence:
        if not (0 <= d.source_index < len(sources)):
            dropped += 1
            continue
        src = sources[d.source_index]
        if not verify_quote(d.quote, src["content"]):
            dropped += 1
            continue
        key = (src["url"], normalise(d.quote))
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            Evidence(url=src["url"], title=src["title"], quote=d.quote.strip(), stance=d.stance, quote_verified=True)
        )
    return kept, dropped


def investigate(claim: Claim, pub_date: str | None = None, on_step=None) -> Claim:
    """Fill in verdict, explanation, evidence and trace for one claim."""
    date, defaulted = effective_date(pub_date)
    date_note = (
        f" (No publication date was given; relative dates were resolved against today, {date}.)"
        if defaulted
        else ""
    )

    if claim.kind != "factual":
        claim.verdict = "not_verifiable"
        claim.explanation = (
            f"This is a {claim.kind}, not a checkable statement of fact, so it was not searched." + date_note
        )
        return claim

    query = call_json(
        prompts.QUERY_SYSTEM, prompts.QUERY_USER.format(claim=claim.text, pub_date=date), QueryPlan, 1000
    ).query.strip() or claim.text

    sources: list[dict] = []
    seen_urls: set[str] = set()
    trace: list[Step] = []
    judgement: Judgement | None = None
    evidence: list[Evidence] = []

    for attempt in range(MAX_SEARCHES):
        final = attempt == MAX_SEARCHES - 1
        depth = "deep" if final else "standard"
        try:
            results = search(query, depth=depth)
        except Exception as e:  # network/API error: record and stop searching
            trace.append(Step(query=query, finding=f"Search failed: {e}", next_action="stop"))
            break
        new = [r for r in results if r["url"] not in seen_urls]
        seen_urls.update(r["url"] for r in new)
        sources.extend(new)

        judgement = call_json(
            prompts.JUDGE_SYSTEM.format(final_note=prompts.JUDGE_FINAL_NOTE if final else ""),
            prompts.JUDGE_USER.format(
                claim=claim.text,
                pub_date=date,
                history=_format_history(trace),
                sources=_format_sources(sources),
            ),
            Judgement,
        )
        evidence, dropped = _verified_evidence(judgement, sources)
        settled = judgement.sufficient and judgement.verdict in DECISIVE and evidence

        finding = (
            f"[{depth}] {len(results)} results ({len(new)} new). Leaning '{judgement.verdict}'; "
            f"{len(evidence)} verified quote(s)"
            + (f", {dropped} unverifiable quote(s) dropped" if dropped else "")
            + ". "
            + (judgement.missing_info if not settled and judgement.missing_info else judgement.explanation)
        )
        next_q = judgement.next_query.strip()
        stop = settled or final or not next_q
        action = f"stop: verdict '{judgement.verdict}'" if stop else f"search again: {next_q}"
        trace.append(Step(query=query, finding=finding, next_action=action))
        if on_step:
            on_step(trace[-1])
        if stop:
            break
        query = next_q

    claim.trace = trace
    claim.evidence = evidence
    if judgement is None:
        claim.verdict = "insufficient"
        claim.explanation = "No evidence could be retrieved." + date_note
    elif judgement.verdict in DECISIVE and not evidence:
        # Core rule: no verdict without verified evidence.
        claim.verdict = "insufficient"
        claim.explanation = (
            f"The model leaned '{judgement.verdict}', but none of its quotes could be verified "
            f"in the source text, so no verdict is given. {judgement.explanation}" + date_note
        )
    else:
        claim.verdict = "insufficient" if judgement.verdict == "not_verifiable" else judgement.verdict
        claim.explanation = judgement.explanation + date_note
    return claim


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Tesla is headquartered in Austin, Texas."
    c = investigate(Claim(text=text, kind="factual"), "2025-03-01", on_step=lambda s: print("  ..", s.query))
    print(c.model_dump_json(indent=2))
