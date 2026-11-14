"""Offline tests for ranking + assessment rules (no keys needed). Run: python -m tests.test_evaluation"""
from backend.evaluation.evaluator import assess
from backend.evaluation.jev import strength
from backend.evaluation.source_ranking import credibility
from backend.models.schemas import Evidence
from backend.models.source import Source


def src(i, publisher, kind="news"):
    return Source(id=f"source_{i}", url=f"https://{publisher}/{i}", title="t", publisher=publisher, content="x", source_type=kind)


def ev(i, source, stance, strength_=5):
    return Evidence(id=f"evidence_{i}", claim_id="claim_1", source_id=source, stance=stance, excerpt="e", strength=strength_)


S = [src(1, "reuters.com"), src(2, "bbc.com"), src(3, "blog.example", "web"), src(4, "sec.gov", "government")]
for s in S:
    s.credibility_score = credibility(s)
assert [s.credibility_score for s in S] == [4, 4, 2, 5]

a = assess("claim_1", [ev(1, "source_1", "supports"), ev(2, "source_2", "supports")], S)
assert a.status == "supported" and a.confidence > 0.5, a
# same publisher twice is one vote, and a lone mid-credibility source cannot decide
a = assess("claim_1", [ev(1, "source_1", "contradicts"), ev(2, "source_1", "contradicts")], S)
assert a.status == "insufficient_evidence", a
# one authoritative source can decide
assert assess("claim_1", [ev(1, "source_4", "contradicts")], S).status == "contradicted"
# mixed evidence
a = assess("claim_1", [ev(1, "source_1", "supports"), ev(2, "source_2", "contradicts")], S)
assert a.status == "partially_supported", a
# neutral / nothing
assert assess("claim_1", [ev(1, "source_1", "neutral")], S).status == "insufficient_evidence"
assert assess("claim_1", [], S).status == "insufficient_evidence"
assert [strength(p) for p in (0.6, 0.9, 1.0)] == [3, 4, 5]
print("evaluation tests passed")

from backend.evaluation.jev import claim_entities, mentions_claim

# --- Jev guard: never classify an excerpt that doesn't name the claim's entities
from backend.extraction.verify import context_for

assert claim_entities("Microsoft controls OpenAI") == [{"microsoft"}, {"openai"}]
assert claim_entities("Elon Musk founded Tesla in 2003") == [{"elon", "musk"}, {"tesla"}]
assert claim_entities("Tesla's revenue grew 40%") == [{"tesla"}]
C = "Microsoft controls OpenAI"
assert not mentions_claim(C, "It does not have a board seat and does not control the company.")
assert not mentions_claim(C, "Google does not control OpenAI.")
assert mentions_claim(C, "Microsoft's stake in OpenAI is 27%.")
assert mentions_claim("Elon Musk founded Tesla", "Musk co-founded Tesla Motors.")
page = "OpenAI was restructured. Microsoft is its largest investor. It does not control the company. Altman is CEO."
ctx = context_for("It does not control the company.", page)
assert "Microsoft is its largest investor." in ctx and "Altman is CEO." in ctx, ctx
assert context_for("not in the page at all here", page) == ""
print("jev guard tests passed")

# --- source selection
from backend.evaluation.source_ranking import rank, select_sources

many = [src(i, f"site{i % 4}.com") for i in range(1, 41)]   # 40 sources from 4 publishers
for i, s in enumerate(many):
    s.relevance_score = 5 - (i % 5)
rank(many)
picked = select_sources(many)
assert len(picked) == 8, len(picked)                          # 4 publishers x 2 each
assert max(sum(p.publisher == q for p in picked) for q in {p.publisher for p in picked}) == 2
assert len(select_sources([src(i, f"s{i}.com") for i in range(30)])) == 10
print("source selection tests passed")


# --- Jev guard: question claims, apostrophes, accents
assert claim_entities("Did Microsoft buy OpenAI?") == [{"microsoft"}, {"openai"}]
assert not mentions_claim("Did Microsoft buy OpenAI?", "She did not know about OpenAI buying anything")
assert mentions_claim("Did Microsoft buy OpenAI?", "Microsoft completed the purchase of a stake in OpenAI")
assert claim_entities("O'Brien founded Acme") == [{"obrien"}, {"acme"}]
assert mentions_claim("O'Brien founded Acme", "Acme was founded by O’Brien in 1999")
assert mentions_claim("Müller founded Acme", "Acme was founded by Muller")

# --- Jev failures degrade instead of raising
import asyncio

import backend.evaluation.jev as jevmod


class BrokenClient:
    def __init__(self, *a, **k):
        raise RuntimeError("no key")


class BadReplyClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def system_one(self, **k):
        return object()  # no .choices


real_client = jevmod.AsyncTypeSafeClient
try:
    for fake in (BrokenClient, BadReplyClient):
        jevmod.AsyncTypeSafeClient = fake
        out = asyncio.run(jevmod.classify_stances("Microsoft controls OpenAI", [("Microsoft does not control OpenAI.", "")]))
        assert out == [None], (fake.__name__, out)
        assert asyncio.run(jevmod.pick_same([("Meta", "", [("Meta Platforms", "")])])) == [None], fake.__name__
finally:
    jevmod.AsyncTypeSafeClient = real_client
print("jev failure tests passed")
