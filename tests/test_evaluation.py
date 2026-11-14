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
