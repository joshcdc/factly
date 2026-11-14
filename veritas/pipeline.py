"""End to end: extract -> investigate claims concurrently -> Report (cached)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from . import cache
from .extract import MAX_CLAIMS, extract_claims
from .investigate import investigate
from .schema import Claim, Report

MAX_WORKERS = 8

# on_progress(event, payload): ("extracted", list[Claim]) | ("claim_done", (index, Claim))
ProgressFn = Callable[[str, object], None]


def run(text: str, pub_date: str | None = None, on_progress: ProgressFn | None = None, use_cache: bool = True) -> Report:
    pub_date = pub_date or None
    claims = extract_claims(text, pub_date)[:MAX_CLAIMS]
    if on_progress:
        on_progress("extracted", claims)

    results: list[Claim | None] = [None] * len(claims)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(claims)))) as pool:
        futures = {pool.submit(investigate, c.model_copy(deep=True), pub_date): i for i, c in enumerate(claims)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # one failing claim must not sink the report
                c = claims[i].model_copy()
                c.verdict = "insufficient"
                c.explanation = f"Investigation failed: {type(e).__name__}: {e}"
                results[i] = c
            if on_progress:
                on_progress("claim_done", (i, results[i]))

    report = Report(input_text=text, pub_date=pub_date, claims=[c for c in results if c is not None])
    if use_cache:
        cache.put(report)
    return report


if __name__ == "__main__":
    import sys

    demo = (
        "Tesla's revenue increased by 40% last year. The company is headquartered in Texas. "
        "Analysts expect its stock price to double next year."
    )
    text = " ".join(sys.argv[1:]) or demo
    r = run(text, "2025-03-01", on_progress=lambda e, p: print("..", e, p[0] if e == "claim_done" else len(p)))
    for c in r.claims:
        print(f"\n[{c.verdict}] {c.text}\n  {c.explanation}")
        for ev in c.evidence:
            print(f"  {'✓' if ev.quote_verified else '?'} ({ev.stance}) \"{ev.quote}\" — {ev.url}")
