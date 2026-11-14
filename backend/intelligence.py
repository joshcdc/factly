"""Agent 2 entry point: sources in, graph out. See AGENT.md "Agent 1 -> Agent 2 hand-off"."""

import asyncio
import re

from backend.evaluation import jev
from backend.evaluation.evaluator import assess
from backend.evaluation.source_ranking import rank
from backend.extraction.extractor import extract
from backend.extraction.verify import context_for, verify_quote
from backend.models.schemas import Edge, Evidence, GraphResult, Node
from backend.models.source import Source

CLAIM_ID = "claim_1"
CONCURRENCY = 6
_SUFFIX = re.compile(r"\b(inc|incorporated|ltd|limited|llc|plc|corp|corporation|co|company|group|the)\b")


def _key(name: str, type_: str) -> tuple[str, str]:
    """Merge key: 'OpenAI Inc.' and 'Open AI' -> ('openai', 'company')."""
    k = _SUFFIX.sub(" ", name.lower()) if type_ == "company" else name.lower()
    return re.sub(r"[^a-z0-9]", "", k) or name.lower(), type_


def analyse(query: str, sources: list[Source], on_progress=None) -> GraphResult:
    """Sync wrapper. Inside an async FastAPI handler, use `await analyse_async(...)` instead."""
    return asyncio.run(analyse_async(query, sources, on_progress))


async def analyse_async(query: str, sources: list[Source], on_progress=None) -> GraphResult:
    say = on_progress or (lambda stage: None)
    rank(sources)

    say("extracting")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(s):
        async with sem:
            try:
                return await extract(query, s)
            except Exception:  # one bad source must not sink the investigation
                return None

    extractions = await asyncio.gather(*(one(s) for s in sources))

    nodes: dict[str, Node] = {CLAIM_ID: Node(id=CLAIM_ID, type="claim", label=query)}
    edges: dict[tuple, Edge] = {}
    ids: dict[tuple, str] = {}
    candidates = []  # (source, excerpt) pairs whose quote was found in the source text

    for s, ex in zip(sources, extractions):
        if ex is None:
            continue
        names = {}
        for ent in ex.entities:
            k = _key(ent.name, ent.type)
            if k not in ids:
                ids[k] = f"entity_{len(ids) + 1}"
                nodes[ids[k]] = Node(id=ids[k], type=ent.type, label=ent.name, description=ent.description)
            node = nodes[ids[k]]
            if s.id not in node.source_ids:
                node.source_ids.append(s.id)
            names[ent.name] = ids[k]
        for r in ex.relationships:
            a, b = names.get(r.subject), names.get(r.object)
            if not a or not b or a == b:
                continue  # relation names an entity the model didn't list: drop it
            e = edges.setdefault((a, b, r.relationship.lower()), Edge(
                id="", source=a, target=b, relationship=r.relationship, description=r.description))
            if s.id not in e.source_ids:
                e.source_ids.append(s.id)
        candidates += [(s, x) for x in ex.excerpts if verify_quote(x.quote, s.content)]
        if names or ex.excerpts:
            # labelled by publisher (a noun), not the headline; title/url go in the details
            nodes[s.id] = Node(id=s.id, type="source", label=s.publisher, description=s.title,
                               properties={"url": s.url, "title": s.title, "credibility": s.credibility_score},
                               source_ids=[s.id])

    # connect the entity cluster to the claim: claim -> each entity the claim names
    for group in jev.claim_entities(query):
        for n in list(nodes.values()):
            if n.type not in ("claim", "source") and group & set(re.findall(r"[a-z0-9][\w&-]*", n.label.lower())):
                edges.setdefault((CLAIM_ID, n.id, "about"), Edge(
                    id="", source=CLAIM_ID, target=n.id, relationship="about"))
                break  # first (earliest-seen) match per name

    say("classifying")
    pairs = [(x.quote, context_for(x.quote, s.content)) for s, x in candidates]
    labels = await jev.classify_stances(query, pairs) if candidates else []
    evidence, unclassified = [], 0
    for (s, x), lab in zip(candidates, labels):
        if lab is None:
            unclassified += 1
            continue
        stance, prob = lab
        ev = Evidence(id=f"evidence_{len(evidence) + 1}", claim_id=CLAIM_ID, source_id=s.id, stance=stance,
                      excerpt=x.quote, reasoning=x.reasoning, strength=jev.strength(prob))
        evidence.append(ev)
        if stance != "neutral":
            e = edges.setdefault((s.id, CLAIM_ID, stance), Edge(
                id="", source=s.id, target=CLAIM_ID, relationship=stance, stance=stance, source_ids=[s.id]))
            e.evidence_ids.append(ev.id)

    say("assessing")
    assessment = assess(CLAIM_ID, evidence, sources)
    if unclassified:
        assessment.explanation += f" {unclassified} excerpt(s) could not be classified (Jev unavailable)."

    out_edges = [e for e in edges.values() if e.source in nodes and e.target in nodes]
    for i, e in enumerate(out_edges, 1):
        e.id = f"edge_{i}"
    order = {"claim": 0, "person": 1, "company": 2, "location": 3, "event": 4, "concept": 5, "source": 6}
    out_nodes = sorted(nodes.values(), key=lambda n: order[n.type])  # stable: keeps first-seen order within a type
    return GraphResult(nodes=out_nodes, edges=out_edges, evidence=evidence, assessments=[assessment])
