"""Stage 1: split input text into atomic, labelled claims."""

from __future__ import annotations

import datetime as dt

from . import prompts
from .llm import call_json
from .schema import Claim, Extraction

MAX_CLAIMS = 8


def effective_date(pub_date: str | None) -> tuple[str, bool]:
    """Return (date string to reason against, whether it was defaulted to today)."""
    if pub_date:
        return pub_date, False
    return dt.date.today().isoformat(), True


def extract_claims(text: str, pub_date: str | None = None) -> list[Claim]:
    date, _defaulted = effective_date(pub_date)
    out = call_json(
        prompts.EXTRACT_SYSTEM.format(max_claims=MAX_CLAIMS),
        prompts.EXTRACT_USER.format(pub_date=date, text=text.strip()),
        Extraction,
        max_tokens=8000,
    )
    return [Claim(text=c.text.strip(), kind=c.kind) for c in out.claims if c.text.strip()][:MAX_CLAIMS]


if __name__ == "__main__":
    import sys

    demo = (
        "Tesla's revenue increased by 40% last year. The company is headquartered in Texas. "
        "Analysts expect its stock price to double next year."
    )
    text = " ".join(sys.argv[1:]) or demo
    for c in extract_claims(text, "2025-03-01"):
        print(f"[{c.kind:10}] {c.text}")
