"""Offline end-to-end test of analyse() with the LLM and Jev stubbed. Run: python -m tests.test_intelligence"""
import backend.intelligence as intel
from backend.extraction.schemas import ExtractedEntity, ExtractedExcerpt, ExtractedRelation, SourceExtraction
from backend.extraction.verify import verify_quote
from backend.models.source import Source

TEXT1 = "Microsoft has invested about $13 billion in OpenAI. Microsoft does not control OpenAI's board."
TEXT2 = "Reuters reports that Microsoft Corp. holds no board seat at OpenAI Inc. and does not control it."
S = [Source(id="source_1", url="https://reuters.com/a", title="A", publisher="reuters.com", content=TEXT1,
            source_type="news"),
     Source(id="source_2", url="https://bbc.com/b", title="B", publisher="bbc.com", content=TEXT2, source_type="news"),
     Source(id="source_3", url="https://x.example/c", title="C", publisher="x.example", content="boom",
            source_type="web")]

# --- verify_quote
assert verify_quote("Microsoft does not control OpenAI's board.", TEXT1)
assert verify_quote("microsoft  does not control OpenAI’s board", TEXT1)        # case, spaces, curly quote
assert not verify_quote("Microsoft does control OpenAI's board.", TEXT1)             # negation dropped
assert not verify_quote("Microsoft has invested about $12 billion in OpenAI", TEXT1)  # number changed
assert not verify_quote("invested about $13 billion ... control OpenAI's board", TEXT1)  # stitched
assert not verify_quote("Microsoft has invested", TEXT1)                             # too short
assert not verify_quote("Microsoft has invested about $1", TEXT1)                    # truncated number


async def fake_extract(claim, s):
    if s.id == "source_3":
        raise RuntimeError("LLM down")
    company = "Microsoft" if s.id == "source_1" else "Microsoft Corp."
    other = "OpenAI" if s.id == "source_1" else "OpenAI Inc."
    quote = ("Microsoft does not control OpenAI's board." if s.id == "source_1"
             else "Microsoft Corp. holds no board seat at OpenAI Inc. and does not control it.")
    return SourceExtraction(
        entities=[ExtractedEntity(name=company, type="company", description="d"),
                  ExtractedEntity(name=other, type="company", description="d")],
        relationships=[ExtractedRelation(subject=company, relationship="invested in", object=other),
                       ExtractedRelation(subject=company, relationship="owns", object="Ghost Co")],  # unknown
        excerpts=[ExtractedExcerpt(quote=quote, reasoning="r"),
                  ExtractedExcerpt(quote="Microsoft fully controls OpenAI and its board", reasoning="made up")])


async def fake_jev(claim, quotes):
    return [("contradicts", 0.97) for _ in quotes]


intel.extract = fake_extract
intel.jev.classify_stances = fake_jev
stages = []
r = intel.analyse("Microsoft controls OpenAI", S, on_progress=stages.append)

by_type = {}
for n in r.nodes:
    by_type.setdefault(n.type, []).append(n)
assert stages == ["extracting", "classifying", "assessing"], stages
assert len(by_type["company"]) == 2, [n.label for n in by_type["company"]]          # merged across sources
assert len(by_type["claim"]) == 1 and by_type["claim"][0].id == "claim_1"
assert {n.id for n in by_type["source"]} == {"source_1", "source_2"}                # failed source skipped
assert len(r.evidence) == 2 and all(e.stance == "contradicts" for e in r.evidence)  # made-up quotes dropped
ids = {n.id for n in r.nodes}
assert all(e.source in ids and e.target in ids for e in r.edges)                     # no dangling edges
assert len({e.id for e in r.edges}) == len(r.edges)
inv = [e for e in r.edges if e.relationship == "invested in"]
assert len(inv) == 1 and inv[0].source_ids == ["source_1", "source_2"]
assert sum(e.stance == "contradicts" for e in r.edges) == 2
a = r.assessments[0]
assert a.status == "contradicted" and a.claim_id == "claim_1", a
assert all(s.credibility_score for s in S)


async def jev_down(claim, quotes):
    return [None for _ in quotes]


intel.jev.classify_stances = jev_down
r = intel.analyse("Microsoft controls OpenAI", S)
assert r.evidence == [] and r.assessments[0].status == "insufficient_evidence"
assert "could not be classified" in r.assessments[0].explanation
print("intelligence tests passed")
