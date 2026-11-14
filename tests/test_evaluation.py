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
assert a.status == "supported" and 0.3 < a.confidence <= 0.5, a      # two sources agree: medium at best
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


# --- confidence: evidence mass with diminishing returns, agreement, authority, coverage; never 1
from backend.evaluation.evaluator import MAX_CONFIDENCE, band


def scenario(spec, unrelated=0):
    """spec: (stance, credibility, strength) per distinct publisher; `unrelated` extra analysed sources with no stance."""
    sources, evidence = [], []
    for i, (stance, c, st) in enumerate(spec, 1):
        sources.append(src(i, f"p{i}.com"))
        sources[-1].credibility_score = c
        evidence.append(ev(i, f"source_{i}", stance, st))
    for k in range(unrelated):
        sources.append(src(100 + k, f"other{k}.com"))
        sources[-1].credibility_score = 3
    return assess("claim_1", evidence, sources)


SUP, CON, NEU = "supports", "contradicts", "neutral"
a = scenario([(SUP, 5, 5)], unrelated=9)                      # one official source, nine analysed sources silent
assert a.status == "supported" and a.confidence == 0.63, a     # no coverage penalty for an official source
assert scenario([(CON, 5, 5)], unrelated=4).confidence == 0.63
assert scenario([(SUP, 5, 5)] * 2).confidence == 0.86          # two official sources: much stronger
assert scenario([(SUP, 5, 3)], unrelated=2).status == "supported" and scenario([(SUP, 5, 3)], unrelated=2).confidence < 0.4  # weak mention: no boost
assert scenario([(SUP, 4, 5)] * 2).confidence == 0.47          # two news sites, nothing else analysed
assert scenario([(SUP, 4, 5)] * 2, unrelated=8).confidence == 0.36   # the rest of the analysed sources say nothing: lower
assert scenario([(SUP, 4, 5)]).status == "insufficient_evidence"
assert scenario([(SUP, 4, 5)]).confidence <= 0.3               # insufficient is capped
live_like = scenario([(SUP, 3 + i % 2, 5) for i in range(8)], unrelated=2)
assert live_like.status == "supported" and 0.7 < live_like.confidence <= MAX_CONFIDENCE, live_like
assert scenario([(SUP, 5, 5)] * 20).confidence == MAX_CONFIDENCE   # never 1
counts = [scenario([(SUP, 4, 5)] * n).confidence for n in (2, 3, 5, 8)]
assert counts == sorted(counts) and len(set(counts)) == 4, counts   # more sources help, with diminishing returns
assert [counts[i + 1] - counts[i] for i in range(3)][0] > [counts[i + 1] - counts[i] for i in range(3)][2] / 2
mixed = scenario([(SUP, 4, 5)] * 2 + [(CON, 4, 5)] * 2)
assert mixed.status == "partially_supported" and 0.5 < mixed.confidence < 0.8, mixed
lopsided = scenario([(SUP, 4, 5)] * 3 + [(CON, 4, 5)])
assert lopsided.status == "partially_supported" and lopsided.confidence < mixed.confidence, (lopsided, mixed)
assert [band(c) for c in (0.1, 0.39, 0.4, 0.7, 0.71, 0.95)] == ["low", "low", "medium", "medium", "high", "high"]
assert "Confidence: medium." in scenario([(SUP, 5, 5)], unrelated=9).explanation
print("confidence tests passed")
