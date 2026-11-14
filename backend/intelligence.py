"""Agent 2 entry point: sources in, graph out. See AGENT.md "Agent 1 -> Agent 2 hand-off"."""

import asyncio
import re
from collections import Counter
from difflib import SequenceMatcher

from backend.evaluation import jev
from backend.evaluation.evaluator import assess
from backend.evaluation.source_ranking import rank, rank_async, select_sources
from backend.extraction import merge
from backend.extraction.extractor import extract, summarise
from backend.extraction.verify import context_for, verify_quote
from backend.models.schemas import Edge, Evidence, GraphResult, Node
from backend.models.source import Source

CLAIM_ID = "claim_1"
CONCURRENCY = 6
_REPORTER = re.compile(r"\b(report(ed|ing|s)?|newspaper|news outlet|outlet|publication|magazine|news agency|"
                       r"broadcaster|journalists?)\b", re.I)
SYMMETRIC = {"partners with", "competes with", "married to", "works with", "allied with"}  # direction-free labels

_STOP = {"the", "a", "an", "of", "and", "in", "on", "for", "to", "is", "its"}


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][\w&-]*", text.lower().replace("'s", "")) if w not in _STOP]


def _same(a: str, b: str) -> bool:
    """Same word, allowing one typo in words of 5+ letters ('jenson' ~ 'jensen')."""
    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def analyse(query: str, sources: list[Source], on_progress=None) -> GraphResult:
    """Sync wrapper. Inside an async FastAPI handler, use `await analyse_async(...)` instead."""
    return asyncio.run(analyse_async(query, sources, on_progress))


async def analyse_async(query: str, sources: list[Source], on_progress=None) -> GraphResult:
    say = on_progress or (lambda stage: None)
    rank(sources)  # rule-based credibility on every source, so the response is consistent
    sources = select_sources(sources)  # only the best ~10 are analysed

    say("extracting")
    ranking = asyncio.create_task(rank_async(query, sources))  # Jev credibility for those 10, alongside extraction
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(s):
        async with sem:
            try:
                return await extract(query, s)
            except Exception:  # one bad source must not sink the investigation
                return None

    extractions = await asyncio.gather(*(one(s) for s in sources))
    await ranking

    # merge entities across all sources once, before any node is made
    canon = await merge.resolve(
        [(e.name, e.type, e.description) for ex in extractions if ex for e in ex.entities], ask=jev.pick_same)

    nodes: dict[str, Node] = {CLAIM_ID: Node(id=CLAIM_ID, type="claim", label=query)}
    edges: dict[tuple, Edge] = {}
    ids: dict[int, str] = {}  # merged-entity gid -> node id
    notes: dict[str, list[tuple[str, str]]] = {}  # node id -> (publisher, what that source said about it)
    candidates = []  # (source, excerpt) pairs whose quote was found in the source text

    for s, ex in zip(sources, extractions):
        if ex is None:
            continue
        names = {}
        for ent in ex.entities:
            c = canon[(ent.name, ent.type)]
            if c.gid not in ids:
                ids[c.gid] = f"entity_{len(ids) + 1}"
                nodes[ids[c.gid]] = Node(id=ids[c.gid], type=c.type, label=c.name, description=c.description,
                                         properties={"aliases": c.aliases} if c.aliases else {})
            node = nodes[ids[c.gid]]
            if s.id not in node.source_ids:
                node.source_ids.append(s.id)
            names[ent.name.lower()] = ids[c.gid]
            notes.setdefault(ids[c.gid], []).append((s.publisher, ent.description))
        for r in ex.relationships:
            a, b = names.get(r.subject.lower()), names.get(r.object.lower())
            if not a or not b or a == b:
                continue  # names an entity the model didn't list, or both ends merged into one: drop it
            label = r.relationship.lower()
            key = (min(a, b), max(a, b), label) if label in SYMMETRIC else (a, b, label)
            e = edges.setdefault(key, Edge(id="", source=a, target=b, relationship=label, description=r.description))
            if s.id not in e.source_ids:
                e.source_ids.append(s.id)
        candidates += [(s, x) for x in ex.excerpts if verify_quote(x.quote, s.content)]
        if names or ex.excerpts:
            # labelled by publisher (a noun), not the headline; title/url go in the details
            nodes[s.id] = Node(id=s.id, type="source", label=s.publisher, description=s.title,
                               properties={"url": s.url, "title": s.title, "credibility": s.credibility_score},
                               source_ids=[s.id])

    # connect the entity cluster to the claim: claim -> each entity the claim names
    claim_tokens = _tokens(query)
    for n in nodes.values():
        # an entity is "about" the claim when every word of its name appears in the claim (typos tolerated),
        # whatever the capitalisation: "Jensen Huang" matches "jenson huang affairs", "OpenAI Foundation" does not
        # match "Microsoft controls OpenAI"
        if n.type in ("claim", "source"):
            continue
        words = merge.words(n.label, drop_suffix=True)  # "OpenAI Inc." counts as "OpenAI"
        if words and all(any(_same(w, c) for c in claim_tokens) for w in words):
            edges.setdefault((CLAIM_ID, n.id, "about"), Edge(
                id="", source=CLAIM_ID, target=n.id, relationship="about"))

    # drop news outlets that are only the story's reporters: no relationships, described as reporting it
    linked = {x for e in edges.values() for x in (e.source, e.target)}
    for nid in [n.id for n in nodes.values()
                if n.type not in ("claim", "source") and n.id not in linked and _REPORTER.search(n.description)]:
        del nodes[nid]

    _connect_orphans(nodes, edges, sources)  # no entity is left without an edge
    _cap_entities(nodes, edges, sources)  # keep the most important entities only...
    _connect_orphans(nodes, edges, sources)  # ...and re-attach any the cut left unconnected
    summaries = asyncio.create_task(_summaries(query, nodes, notes))  # runs alongside Jev classification

    say("classifying")
    pairs =[(x.quote, context_for(x.quote, s.content)) for s, x in candidates]
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

    for nid, text in await summaries:
        if text:
            nodes[nid].properties["summary"] = text

    say("assessing")
    assessment = assess(CLAIM_ID, evidence, sources)
    if unclassified:
        assessment.explanation += f" {unclassified} excerpt(s) could not be classified (Jev unavailable)."

    out_edges = [e for e in edges.values() if e.source in nodes and e.target in nodes]
    for i, e in enumerate(out_edges, 1):
        e.id = f"edge_{i}"
    order = {"claim": 0, "person": 1, "company": 2, "location": 3, "event": 4, "concept": 5, "source": 6}
    out_nodes = sorted(nodes.values(), key=lambda n: order[n.type])  # stable: keeps first-seen order within a type
    _prioritise(out_nodes, out_edges, sources, evidence)
    return GraphResult(nodes=out_nodes, edges=out_edges, evidence=evidence, assessments=[assessment])


async def _summaries(query: str, nodes: dict[str, Node], notes: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str | None]]:
    """A short summary per entity from what each source said about it. One mention that is already short is used
    as is (no model call); failures give None and the frontend falls back to `description`."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(n: Node):
        mentions = list(dict.fromkeys(m for m in notes.get(n.id, []) if m[1]))
        texts = {t for _, t in mentions}
        if len(texts) <= 1:
            only = next(iter(texts), "")
            if len(only.split()) <= 40:
                return n.id, only or None
        async with sem:
            return n.id, await summarise(query, n.label, n.type, mentions)

    return list(await asyncio.gather(*(one(n) for n in nodes.values() if n.type not in ("claim", "source"))))


FALLBACK = "mentioned with"  # not a real relationship: lowest weight, so the frontend can fade or hide it
MAX_ENTITIES_OUT = 12  # entity nodes returned per investigation; the rest are cut by priority


def _support(ids: list[str], src: dict[str, Source]) -> int:
    """Credibility of the independent publishers behind `ids`: one vote per publisher (its best credibility),
    because repeated pages from one publisher are not independent."""
    best: dict[str, int] = {}
    for i in ids:
        if i in src:
            best[src[i].publisher] = max(best.get(src[i].publisher, 0), src[i].credibility_score or 2)
    return sum(best.values())


def _cap_entities(nodes: dict[str, Node], edges: dict[tuple, Edge], sources: list[Source],
                  limit: int = MAX_ENTITIES_OUT) -> None:
    """Keep at most `limit` entities: first the claim's own subjects, then the highest priority. Drops the rest
    and every edge that touched them."""
    ents = [n for n in nodes.values() if n.type not in ("claim", "source")]
    if len(ents) <= limit:
        return
    src = {s.id: s for s in sources}
    degree = Counter(x for e in edges.values() if e.relationship not in ("about", FALLBACK) for x in (e.source, e.target))
    named = {e.target for e in edges.values() if e.relationship == "about"}  # always kept
    ranked = sorted((n for n in ents if n.id not in named),
                    key=lambda n: _support(n.source_ids, src) + 2 * degree[n.id], reverse=True)
    keep = named | {n.id for n in ranked[:max(0, limit - len(named))]}
    for n in ents:
        if n.id not in keep:
            del nodes[n.id]
    for k in [k for k, e in edges.items() if e.source not in nodes or e.target not in nodes]:
        del edges[k]


def _connect_orphans(nodes: dict[str, Node], edges: dict[tuple, Edge], sources: list[Source]) -> None:
    """Give every entity with no edge one low-priority `mentioned with` edge: to the connected entity it shares
    the most sources with (ties: the more connected one), else to the claim."""
    pub = {s.id: s.publisher for s in sources}
    ents = [n for n in nodes.values() if n.type not in ("claim", "source")]
    linked = {x for e in edges.values() for x in (e.source, e.target)}
    degree = Counter(x for e in edges.values() if e.relationship not in ("about", FALLBACK) for x in (e.source, e.target))
    connected = [n for n in ents if n.id in linked]
    for n in ents:
        if n.id in linked:
            continue
        shared = {m.id: sorted(set(m.source_ids) & set(n.source_ids)) for m in connected if m.id != n.id}
        shared = {k: v for k, v in shared.items() if v}
        if shared:
            best = max(shared, key=lambda k: (len(shared[k]), degree[k]))
            where = ", ".join(sorted({pub[s] for s in shared[best] if s in pub}))
            edges[(n.id, best, FALLBACK)] = Edge(id="", source=n.id, target=best, relationship=FALLBACK,
                                                 description=f"Both appear in {where}", source_ids=shared[best])
        else:  # shares no source with a connected entity: hang it off the claim so it still shows
            edges[(n.id, CLAIM_ID, FALLBACK)] = Edge(id="", source=n.id, target=CLAIM_ID, relationship=FALLBACK,
                                                     description="Appears in the sources", source_ids=n.source_ids)


def _prioritise(nodes: list[Node], edges: list[Edge], sources: list[Source], evidence: list[Evidence]) -> None:
    """Display priority from data we already have (no API calls), all in 0-1:
    entity node  properties["priority"] = credibility of the independent publishers that mention it + 2 x its connections
    relationship Edge.weight            = credibility of the independent publishers that state it
    source node  properties["priority"] = its credibility; claim = 1; stance edge weight = evidence strength x credibility
    """
    src = {s.id: s for s in sources}
    strength = {e.id: e.strength for e in evidence}

    def support(ids: list[str]) -> int:
        return _support(ids, src)

    rel = [e for e in edges if not e.stance and e.relationship not in ("about", FALLBACK)]
    degree = Counter(x for e in rel for x in (e.source, e.target))
    ents = [n for n in nodes if n.type not in ("claim", "source")]
    raw = {n.id: support(n.source_ids) + 2 * degree[n.id] for n in ents}
    top = max(raw.values(), default=0) or 1
    for n in ents:
        n.properties["priority"] = round(raw[n.id] / top, 2)
        n.properties["sources"] = len([i for i in n.source_ids if i in src])
        n.properties["publishers"] = len({src[i].publisher for i in n.source_ids if i in src})
    edge_raw = {e.id: support(e.source_ids) for e in rel}
    edge_top = max(edge_raw.values(), default=0) or 1
    for e in rel:
        e.weight = round(edge_raw[e.id] / edge_top, 2)
    for n in nodes:
        if n.type == "claim":
            n.properties["priority"] = 1.0
        elif n.type == "source":
            n.properties["priority"] = round((src[n.id].credibility_score or 2) / 5, 2)
    for e in edges:
        if e.stance:
            best = max((strength.get(i, 3) for i in e.evidence_ids), default=3)
            e.weight = round(max(0.1, best / 5 * (src[e.source].credibility_score or 2) / 5), 2)
        elif e.relationship == "about":
            e.weight = 1.0
        elif e.relationship == FALLBACK:
            e.weight = 0.1
