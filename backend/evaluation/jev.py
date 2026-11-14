"""Stance classification with Jev (TypeSafe AI). Jev alone decides stance; no LLM fallback."""

import asyncio

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Choice

from backend.models.schemas import Stance

load_dotenv()

MODEL = "jev-1.13.0"  # pinned: thresholds tuned on one version may not hold on the next
MIN_PROB = 0.6  # below this the label is not trusted and becomes "neutral"
CONCURRENCY = 8

QUESTION = Choice(
    instructions="Does `excerpt` support or contradict `claim`?",
    criteria={
        "supports": "The excerpt states or clearly implies the claim is true",
        "contradicts": "The excerpt states or clearly implies the claim is false or incompatible",
        "neutral": "The excerpt does not address the claim, or only shares keywords with it",
    },
)


async def classify_stances(claim: str, excerpts: list[str]) -> list[tuple[Stance, float] | None]:
    """One (stance, probability) per excerpt, in order. None where Jev failed (unclassified)."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, excerpt: str):
        async with sem:
            try:
                r = await client.system_one(
                    state={"claim": claim, "excerpt": excerpt}, questions={"stance": QUESTION}
                )
            except Exception:  # SDK already retried 429s; anything left means "unclassified"
                return None
        probs = r.choices["stance"].probabilities
        label = max(probs, key=probs.get)
        return (label, probs[label]) if probs[label] >= MIN_PROB else ("neutral", probs[label])

    async with AsyncTypeSafeClient(model=MODEL) as client:
        return list(await asyncio.gather(*(one(client, e) for e in excerpts)))


def strength(prob: float) -> int:
    """Jev probability of the winning label -> Evidence.strength 1-5."""
    return max(1, min(5, round(prob * 5)))
