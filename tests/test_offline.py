"""Offline end-to-end test: stubs Linkup + LLM so the agent loop, quote filter and pipeline run with no keys."""
from veritas import investigate as inv, extract as ext, pipeline
from veritas.schema import Extraction, ExtractedClaim, QueryPlan, Judgement, EvidenceDraft, Claim

PAGES = {
    "q1": [{"title": "Blog", "url": "https://blog.example/tesla", "content": "Tesla is a car company. Elon Musk tweets a lot.", "published_at": None}],
    "q2": [{"title": "Tesla 10-K 2024", "url": "https://ir.tesla.com/10k", "content": "Total revenues were $97.69 billion in 2024, compared to $96.77 billion in 2023.", "published_at": None}],
}
searches = []
def fake_search(q, depth="standard", max_results=6):
    searches.append((q, depth)); return PAGES.get(q, [])

judge_calls = {"n": 0}
def fake_call_json(system, user, cls, max_tokens=16000):
    if cls is Extraction:
        return Extraction(claims=[ExtractedClaim(text="Tesla's revenue increased by 40% in 2024.", kind="factual"),
                                  ExtractedClaim(text="Tesla's stock price will double in 2026.", kind="prediction")])
    if cls is QueryPlan: return QueryPlan(query="q1")
    judge_calls["n"] += 1
    if judge_calls["n"] == 1:   # keyword-only source -> insufficient, ask again
        return Judgement(sufficient=False, verdict="insufficient", explanation="Only a blog.", evidence=[],
                         missing_info="Need annual revenue figures.", next_query="q2")
    return Judgement(sufficient=True, verdict="contradicted", explanation="Revenue grew ~1%, not 40%.",
                     evidence=[EvidenceDraft(source_index=1, quote="Total revenues were $97.69 billion in 2024", stance="contradicts"),
                               EvidenceDraft(source_index=1, quote="revenue rose 40% to a record", stance="supports"),   # hallucinated
                               EvidenceDraft(source_index=9, quote="anything at all here ok", stance="supports")],      # bad index
                     missing_info="", next_query="")

inv.search = fake_search; inv.call_json = fake_call_json; ext.call_json = fake_call_json

r = pipeline.run("demo text", "2025-03-01", use_cache=False)
f, p = r.claims
assert p.verdict == "not_verifiable" and not p.trace, p
assert f.verdict == "contradicted", f
assert [e.quote for e in f.evidence] == ["Total revenues were $97.69 billion in 2024"], f.evidence
assert all(e.quote_verified for e in f.evidence)
assert len(f.trace) == 2 and f.trace[0].next_action.startswith("search again") and "2 unverifiable" in f.trace[1].finding
assert searches == [("q1", "standard"), ("q2", "standard")], searches

# Decisive verdict with zero verifiable quotes must be downgraded to insufficient.
judge_calls["n"] = 1; searches.clear()
def bad_judge(system, user, cls, max_tokens=16000):
    if cls is QueryPlan: return QueryPlan(query="q2")
    return Judgement(sufficient=True, verdict="supported", explanation="x", missing_info="", next_query="",
                     evidence=[EvidenceDraft(source_index=0, quote="Tesla revenue grew forty percent", stance="supports")])
inv.call_json = bad_judge
c = inv.investigate(Claim(text="t", kind="factual"), None)
assert c.verdict == "insufficient" and c.evidence == [] and "No publication date" in c.explanation, c

# Budget: never-sufficient judge -> exactly 3 searches, last one deep.
searches.clear()
def never(system, user, cls, max_tokens=16000):
    if cls is QueryPlan: return QueryPlan(query="a")
    return Judgement(sufficient=False, verdict="insufficient", explanation="no", evidence=[], missing_info="m", next_query="b")
inv.call_json = never
c = inv.investigate(Claim(text="t", kind="factual"), "2025-01-01")
assert [d for _, d in searches] == ["standard", "standard", "deep"] and c.verdict == "insufficient", searches
print("offline tests passed")
