"""Stance classification with Jev (TypeSafe AI). Jev alone decides stance; no LLM fallback."""

import asyncio
import re

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Choice, Score

from backend.models.schemas import Stance
from backend.models.source import Source
from backend.textutil import fold, tokens

load_dotenv()

MODEL = "jev-1.13.0"  # pinned: thresholds tuned on one version may not hold on the next
MIN_PROB = 0.6  # below this the label is not trusted and becomes "neutral"
CONCURRENCY = 8

QUESTION = Choice(
    instructions=(
        "Does `excerpt` support or contradict `claim`? Use `context` (the surrounding sentences) only to "
        "work out who or what the excerpt refers to. Judge the excerpt itself, not the context. If it is not "
        "clear that the excerpt is about the specific people or organisations named in `claim`, answer neutral."
    ),
    criteria={
        "supports": "The excerpt, about the entities in the claim, states or clearly implies the claim is true",
        "contradicts": "The excerpt, about the entities in the claim, states or clearly implies the claim is false",
        "neutral": "The excerpt does not address the claim, only shares keywords with it, or it is unclear "
                   "who or what it refers to",
    },
)


_STOP = {"the", "a", "an", "in", "on", "of", "and", "or", "is", "was", "its", "their", "this", "that"}
# capitalised only because they start a question ("Did Microsoft buy OpenAI?"), so not part of any name
_QUESTION = {"did", "does", "do", "is", "are", "was", "were", "has", "have", "had", "can", "could", "will", "would",
             "should", "may", "might", "why", "how", "what", "who", "whom", "when", "where", "which"}


def claim_entities(claim: str) -> list[set[str]]:
    """Named things in the claim: runs of capitalised words ('Elon Musk', 'OpenAI'), as folded token sets."""
    groups, cur = [], set()
    for w in re.findall(r"[^\W_][\w&'’-]*", claim):
        t = tokens(w)
        if w[0].isupper() and t and fold(w) not in _STOP and fold(w) not in _QUESTION:
            cur.update(t)
        elif cur:
            groups.append(cur)
            cur = set()
    return groups + [cur] if cur else groups


def mentions_claim(claim: str, text: str) -> bool:
    """Every named entity in the claim must appear (any of its words) in the excerpt or its context."""
    words = set(tokens(text))
    return all(g & words for g in claim_entities(claim))


async def classify_stances(claim: str, excerpts: list[tuple[str, str]]) -> list[tuple[Stance, float] | None]:
    """excerpts: (excerpt, surrounding context) pairs. One (stance, probability) per excerpt, in order.
    None where Jev failed (unclassified). Jev never sees the page title, URL or publisher."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, item: tuple[str, str]):
        excerpt, context = item
        if not mentions_claim(claim, f"{excerpt} {context}"):
            return ("neutral", 1.0)  # can't tell who it is about: never let Jev guess
        async with sem:
            try:
                r = await client.system_one(
                    state={"claim": claim, "excerpt": excerpt, "context": context or "(none)"},
                    questions={"stance": QUESTION},
                )
                probs = r.choices["stance"].probabilities
                label = max(probs, key=probs.get)
            except Exception:  # SDK already retried 429s; an error or malformed reply means "unclassified"
                return None
        return (label, probs[label]) if probs[label] >= MIN_PROB else ("neutral", probs[label])

    try:
        async with AsyncTypeSafeClient(model=MODEL) as client:
            return list(await asyncio.gather(*(one(client, e) for e in excerpts)))
    except Exception:  # no key / Jev unreachable: every excerpt stays unclassified, the run carries on
        return [None] * len(excerpts)


CREDIBILITY = Score(
    instructions=(
        "How credible is this source as evidence about `claim`? Judge the publisher and the page itself: "
        "is it an original or authoritative source, does it have editorial standards, does it cite where "
        "its facts come from?"
    ),
    criteria=[  # position = score 0..4, mapped to credibility_score 1..5
        "Unreliable: content farm, SEO or AI-generated aggregator, spam, or unsourced assertions",
        "Low: personal blog, forum, social media post, or a site that rewrites others' reporting without sources",
        "Moderate: niche or trade publication, or secondary reporting that names its sources",
        "High: established news organisation with editorial standards, or a reputable reference work",
        "Authoritative: the primary source for this claim, e.g. an official filing, regulator, statistics office, "
        "peer-reviewed study, or the organisation's own official announcement",
    ],
)
PAGE_CHARS = 1500  # enough of the page for Jev to judge its quality


async def rate_credibility(claim: str, sources: list[Source]) -> list[int | None]:
    """Jev credibility 1-5 per source, in order. None where Jev failed (caller keeps the rule-based score)."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, s: Source):
        async with sem:
            try:
                r = await client.system_one(
                    state={"claim": claim, "url": s.url, "publisher": s.publisher, "title": s.title,
                           "page_excerpt": s.content[:PAGE_CHARS]},
                    questions={"credibility": CREDIBILITY},
                )
            except Exception:
                return None
        return max(1, min(5, 1 + round(r.scores["credibility"].score)))

    try:
        async with AsyncTypeSafeClient(model=MODEL) as client:
            return list(await asyncio.gather(*(one(client, s) for s in sources)))
    except Exception:  # no key / Jev unreachable: keep the rule-based scores
        return [None] * len(sources)


SAME_PROB = 0.9  # entity merging: a wrong merge is worse than a duplicate


async def pick_same(items: list[tuple[str, str, list[tuple[str, str]]]]) -> list[int | None]:
    """items: (entity name, description, [(candidate name, description), ...]).
    Per item: the index of the candidate that is the very same real-world thing, or None."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, item):
        name, desc, cands = item
        criteria = {f"c{k}": f"{n}: {d or 'no description'}" for k, (n, d) in enumerate(cands)}
        criteria["none"] = ("None of these is the very same thing (it may be a part, subsidiary, parent, product, "
                            "event or person related to it, but not the same entity)")
        question = Choice(
            instructions=(
                "Is `entity` just another name for exactly one of the options, the very same real-world person, "
                "organisation or thing? Answer none if an option is only related to it: a subsidiary, parent, "
                "foundation, division, product, event or member of it."
            ),
            criteria=criteria,
        )
        async with sem:
            try:
                r = await client.system_one(state={"entity": name, "entity_description": desc or "none"},
                                            questions={"same": question})
                probs = r.choices["same"].probabilities
                best = max(probs, key=probs.get)
                return int(best[1:]) if best != "none" and probs[best] >= SAME_PROB else None
            except Exception:  # error or malformed reply: no merge
                return None

    try:
        async with AsyncTypeSafeClient(model=MODEL) as client:
            return list(await asyncio.gather(*(one(client, it) for it in items)))
    except Exception:  # no key / Jev unreachable: no Jev merges, rules still apply
        return [None] * len(items)


def strength(prob: float) -> int:
    """Jev probability of the winning label -> Evidence.strength 1-5."""
    return max(1, min(5, round(prob * 5)))
