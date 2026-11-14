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


async def _none(n):
    return [None] * n


async def fake_jev(claim, quotes):
    return [("contradicts", 0.97) for _ in quotes]


# keep this suite hermetic: no live Jev or LLM calls for credibility, merging or summaries
summary_calls = []


async def fake_rank(claim, sources):
    intel.rank(sources)


async def fake_pick(items):
    return [None] * len(items)


async def fake_summarise(claim, name, type_, mentions):
    summary_calls.append((name, list(mentions)))
    return f"{name}: summary of {len(mentions)} mention(s)"


intel.rank_async = fake_rank
intel.jev.pick_same = fake_pick
intel.summarise = fake_summarise
intel.extract = fake_extract
intel.jev.classify_stances = fake_jev
intel.jev.rate_credibility = lambda claim, sources: _none(len(sources))  # offline: keep rule-based scores
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
assert {n.label for n in by_type["source"]} == {"reuters.com", "bbc.com"}            # nouns, not headlines
assert not any(e.relationship == "mentions" for e in r.edges)
about = {e.target for e in r.edges if e.relationship == "about"}
assert {n.label for n in r.nodes if n.id in about} == {"Microsoft", "OpenAI"}        # claim linked to its entities
assert [n.type for n in r.nodes][0] == "claim" and [n.type for n in r.nodes][-1] == "source"

# --- extractor clean-up helpers
from backend.extraction.extractor import clean_label, is_noun_name

assert is_noun_name("Microsoft") and is_noun_name("OpenAI Group PBC") and is_noun_name("U.S. Treasury")
assert not is_noun_name("Azure growth beats estimates. Shares rise")
assert not is_noun_name("Opinion: Microsoft is really in charge")
assert not is_noun_name("Microsoft has effective control over OpenAI's strategy")              # > 5 words
assert clean_label("Has invested in") == "invested in" and clean_label("controls") == "controls"
assert clean_label("has exclusive rights to sell OpenAI models through") == ""


async def jev_down(claim, quotes):
    return [None for _ in quotes]


intel.jev.classify_stances = jev_down
r = intel.analyse("Microsoft controls OpenAI", S)
assert r.evidence == [] and r.assessments[0].status == "insufficient_evidence"
assert "could not be classified" in r.assessments[0].explanation
print("intelligence tests passed")

# --- claim linking works for lowercase claims and typos
from backend.extraction.merge import same_word as _same, words as _tokens

assert _same("jenson", "jensen") and not _same("huang", "huge") and _same("openai", "openai")
assert _tokens("Jensen Huang's affairs") == ["jensen", "huang", "affairs"]
print("claim linking tests passed")

# --- reporter-only outlets are dropped, outlets that take part in events are kept
async def extract_with_outlets(claim, s):
    return SourceExtraction(
        entities=[ExtractedEntity(name="Microsoft", type="company", description="d"),
                  ExtractedEntity(name="OpenAI", type="company", description="d"),
                  ExtractedEntity(name="Reuters", type="company", description="News agency that reported the deal"),
                  ExtractedEntity(name="The Times", type="company", description="Newspaper sued by OpenAI")],
        relationships=[ExtractedRelation(subject="Microsoft", relationship="invested in", object="OpenAI"),
                       ExtractedRelation(subject="OpenAI", relationship="sued", object="The Times")],
        excerpts=[])

intel.extract = extract_with_outlets
intel.jev.classify_stances = fake_jev
labels = {n.label for n in intel.analyse("Microsoft controls OpenAI", S[:1]).nodes}
assert "Reuters" not in labels and "The Times" in labels and "Microsoft" in labels, labels
print("reporter filter tests passed")

# --- display priority
from backend.models.schemas import Edge as _Edge, Node as _Node


def build(sources_n, nodes, edges):
    srcs = [Source(id=f"source_{i}", url="u", title="t", publisher=f"p{i}.com", content="x", source_type="news")
            for i in range(1, sources_n + 1)]
    for s, c in zip(srcs, [5, 4, 3, 2, 1][:sources_n]):
        s.credibility_score = c
    intel._prioritise(nodes, edges, srcs, [])
    return nodes, edges

hub = _Node(id="e1", type="company", label="Hub", source_ids=["source_1", "source_2", "source_3"])
mid = _Node(id="e2", type="person", label="Mid", source_ids=["source_1"])
orphan = _Node(id="e3", type="person", label="Orphan", source_ids=["source_4"])
edge_a = _Edge(id="x1", source="e1", target="e2", relationship="leads", source_ids=["source_1", "source_2"])
edge_b = _Edge(id="x2", source="e1", target="e2", relationship="part of", source_ids=["source_4"])
build(4, [hub, mid, orphan], [edge_a, edge_b])
assert hub.properties["priority"] == 1.0
assert hub.properties["priority"] > mid.properties["priority"] > orphan.properties["priority"] > 0
assert edge_a.weight == 1.0 and 0 < edge_b.weight < edge_a.weight
assert all(0 <= n.properties["priority"] <= 1 for n in (hub, mid, orphan))

# an edge repeated by two pages of one publisher is still one vote
dup = [Source(id=f"source_{i}", url="u", title="t", publisher="same.com", content="x", source_type="news")
       for i in (1, 2)]
for s in dup:
    s.credibility_score = 4
n1 = _Node(id="e1", type="company", label="A", source_ids=["source_1", "source_2"])
e1 = _Edge(id="x1", source="e1", target="e2", relationship="owns", source_ids=["source_1", "source_2"])
intel._prioritise([n1], [e1], dup, [])
assert n1.properties["priority"] == 1.0 and e1.weight == 1.0

# full pipeline output carries priority and weight on everything
intel.extract = fake_extract
intel.jev.classify_stances = fake_jev
r = intel.analyse("Microsoft controls OpenAI", S)
assert all("priority" in n.properties and 0 <= n.properties["priority"] <= 1 for n in r.nodes)
assert all(0 <= e.weight <= 1 for e in r.edges)
assert next(n for n in r.nodes if n.type == "claim").properties["priority"] == 1.0
assert all(e.weight == 1.0 for e in r.edges if e.relationship == "about")
assert all(0.1 <= e.weight <= 1 for e in r.edges if e.stance)
print("priority tests passed")

# --- no entity is left without an edge
async def extract_with_orphans(claim, s):
    if s.id == "source_1":
        return SourceExtraction(
            entities=[ExtractedEntity(name="Microsoft", type="company", description="d"),
                      ExtractedEntity(name="OpenAI", type="company", description="d"),
                      ExtractedEntity(name="Dan Ives", type="person", description="Analyst who commented")],  # no relationship
            relationships=[ExtractedRelation(subject="Microsoft", relationship="invested in", object="OpenAI"),
                           ExtractedRelation(subject="Microsoft", relationship="alleged ties to", object="OpenAI")],
            excerpts=[])
    if s.id == "source_2":  # an entity that shares no source with anything connected
        return SourceExtraction(entities=[ExtractedEntity(name="Marco Rubio", type="person", description="d")],
                                relationships=[], excerpts=[])
    return None

intel.extract = extract_with_orphans
r = intel.analyse("Microsoft controls OpenAI", S)
ents = [n for n in r.nodes if n.type not in ("claim", "source")]
touched = {x for e in r.edges for x in (e.source, e.target)}
assert ents and all(n.id in touched for n in ents), [n.label for n in ents if n.id not in touched]
lab = {n.id: n.label for n in r.nodes}
fb = {lab[e.source]: (lab[e.target], e) for e in r.edges if e.relationship == "mentioned with"}
assert set(fb) == {"Dan Ives", "Marco Rubio"}, fb
assert fb["Dan Ives"][0] in ("Microsoft", "OpenAI") and "reuters.com" in fb["Dan Ives"][1].description
assert fb["Marco Rubio"][0] == "Microsoft controls OpenAI"                        # shares no source: hangs off the claim
assert all(e.weight == 0.1 for _, e in fb.values())
prio = {n.label: n.properties["priority"] for n in ents}
assert prio["Dan Ives"] < prio["Microsoft"] and prio["Microsoft"] == 1.0           # fallback edges don't inflate priority
alleged = [e for e in r.edges if e.relationship == "alleged ties to"]
assert len(alleged) == 1

from backend.extraction.extractor import clean_label as _cl
assert _cl("Alleged affair with") == "alleged affair with" and _cl("allegedly has a very long label here") == ""
print("orphan tests passed")

# --- entity cap: the claim's subjects and best-supported entities survive; nothing is left unconnected
MINOR = [f"{a} {b}" for a, b in zip(
    ["Ana", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lena", "Milo", "Nora", "Omar"],
    ["Vance", "Stone", "Reed", "Park", "Long", "Hale", "Cruz", "Frost", "Moon", "Wells", "Pike", "Gray", "Dunn",
     "Shaw", "Lowe"])]


async def extract_many(claim, s):
    ents = [ExtractedEntity(name="Microsoft", type="company", description="d"),
            ExtractedEntity(name="OpenAI", type="company", description="d")]
    ents += [ExtractedEntity(name=n, type="person", description="d") for n in MINOR]
    rels = [ExtractedRelation(subject="Microsoft", relationship="invested in", object="OpenAI")]
    if s.id == "source_1":   # two minor people are well connected inside source_1, the rest hang on nothing
        rels += [ExtractedRelation(subject="Ana Vance", relationship="works for", object="Microsoft"),
                 ExtractedRelation(subject="Ben Stone", relationship="works for", object="Microsoft"),
                 ExtractedRelation(subject="Ana Vance", relationship="partners with", object="Ben Stone")]
    return SourceExtraction(entities=ents, relationships=rels, excerpts=[])

intel.extract = extract_many
r = intel.analyse("Microsoft controls OpenAI", S)
ents = [n for n in r.nodes if n.type not in ("claim", "source")]
labels = {n.label for n in ents}
assert len(ents) == intel.MAX_ENTITIES_OUT == 12, len(ents)
assert {"Microsoft", "OpenAI"} <= labels                                         # the claim's own subjects always stay
assert {"Ana Vance", "Ben Stone"} <= labels                              # connected entities beat unconnected ones
touched = {x for e in r.edges for x in (e.source, e.target)}
assert all(n.id in touched for n in ents)                                        # still no orphans after the cut
ids = {n.id for n in r.nodes}
assert all(e.source in ids and e.target in ids for e in r.edges)                 # no edge points at a dropped entity
assert intel.MAX_ENTITIES_OUT >= len([n for n in ents if n.properties["priority"] > 0])
print("entity cap tests passed")


# --- entity summaries and counts
async def extract_notes(claim, s):
    d1 = "US software company that has invested heavily in OpenAI"
    d2 = "Technology giant and OpenAI's largest outside investor, according to filings"
    return SourceExtraction(
        entities=[ExtractedEntity(name="Microsoft", type="company", description=d1 if s.id == "source_1" else d2),
                  ExtractedEntity(name="OpenAI", type="company", description="AI lab")],   # same text in both sources
        relationships=[ExtractedRelation(subject="Microsoft", relationship="invested in", object="OpenAI")],
        excerpts=[])

intel.extract = extract_notes
summary_calls.clear()
r = intel.analyse("Microsoft controls OpenAI", S)
by = {n.label: n for n in r.nodes}
assert by["Microsoft"].properties["summary"] == "Microsoft: summary of 3 mention(s)"       # different notes from 3 sources -> model call
assert by["OpenAI"].properties["summary"] == "AI lab"                                         # one short note -> used as is
assert [c[0] for c in summary_calls] == ["Microsoft"], summary_calls                          # so only one model call
assert by["Microsoft"].properties["sources"] == 3 and by["Microsoft"].properties["publishers"] == 3
assert all("summary" not in n.properties for n in r.nodes if n.type in ("claim", "source"))


async def summaries_fail(claim, name, type_, mentions):
    return None

intel.summarise = summaries_fail
r = intel.analyse("Microsoft controls OpenAI", S)                                           # a failed summary never fails the run
assert "summary" not in {n.label: n for n in r.nodes}["Microsoft"].properties
assert {n.label: n for n in r.nodes}["Microsoft"].description                                # description remains as the fallback
print("summary tests passed")


# --- review fixes: quote boundaries, sentence-spanning context, failures are reported
from backend.extraction.verify import context_for

assert not verify_quote("The deal was worth about $13", "The deal was worth about $13,000 per seat.")
assert not verify_quote("6 percent of voters said they agreed", "In total 16 percent of voters said they agreed.")
assert not verify_quote("6 percent of voters said they agreed", "In total 6.5 percent of voters said they agreed.")
assert not verify_quote("Azure revenue grew by 40.", "Azure revenue grew by 40.5% in the quarter.")
assert not verify_quote("ten percent of voters said they agreed", "In total, often percent of voters said they agreed")  # starts inside a word
assert verify_quote("Azure revenue grew by 40% last year.", "Azure revenue grew by 40% last year. Other segments fell.")
assert verify_quote("Azure revenue grew by 40", "Azure revenue grew by 40 percent last year")
assert verify_quote("the stake was worth about $13",                                                          # a later match counts
                    "an old note said the stake was worth about $13,000 here. Later the stake was worth about $13 billion.")

page = ("OpenAI restructured last year. Microsoft is its largest investor. It denied it. "
        "Microsoft does not control OpenAI. Altman is CEO.")
ctx = context_for("It denied it. Microsoft does not control OpenAI.", page)                                 # quote spans 2 sentences
assert "largest investor" in ctx and "Altman is CEO." in ctx, ctx


async def extract_fail(claim, s):
    raise RuntimeError("401 invalid x-api-key")

intel.extract = extract_fail
try:
    intel.analyse("Microsoft controls OpenAI", S)
    raise SystemExit("expected AnalysisError when no source can be read")
except intel.AnalysisError as e:
    assert "Could not read any of the 3 sources (RuntimeError)" in str(e) and "401" not in str(e), str(e)


async def extract_one_fails(claim, s):
    if s.id == "source_3":
        raise RuntimeError("boom")
    return await extract_notes(claim, s)

intel.extract = extract_one_fails
r = intel.analyse("Microsoft controls OpenAI", S)                                                           # partial failure is reported
assert "1 of 3 sources could not be read." in r.assessments[0].explanation, r.assessments[0].explanation
print("review fix tests passed")
