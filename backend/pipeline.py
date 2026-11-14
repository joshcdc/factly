"""Orchestrates one investigation: research (Agent 1) -> extraction/evaluation (Agent 2) -> response.

Handoff contract for Agent 2: provide `backend/extraction/extractor.py` with

    def extract_graph(query: str, mode: str, sources: list[Source]) -> GraphResult | dict

returning nodes, edges, evidence and assessments that reference the given source ids.
Until that module exists, `fallback_graph` builds a query + sources graph so the frontend has real data.
"""

import logging

from pydantic import ValidationError

from backend.models.schemas import Edge, GraphResult, InvestigationResponse, Node, Source
from backend.research import retrieval
from backend.research.linkup import ResearchError

log = logging.getLogger("fakta.pipeline")


def fallback_graph(query: str, mode: str, sources: list[Source]) -> GraphResult:
    root = Node(id="query_1", type="claim" if mode == "claim" else "concept", label=query,
                description="The claim under investigation" if mode == "claim" else "The investigated topic")
    nodes = [root] + [
        Node(id=s.id, type="source", label=s.title, description=s.publisher,
             properties={"url": s.url, "source_type": s.source_type, "published_at": s.published_at},
             source_ids=[s.id])
        for s in sources
    ]
    edges = [
        Edge(id=f"edge_{i + 1}", source=s.id, target=root.id, relationship="discusses", source_ids=[s.id])
        for i, s in enumerate(sources)
    ]
    return GraphResult(nodes=nodes, edges=edges)


def _extract(query: str, mode: str, sources: list[Source]) -> GraphResult:
    try:
        from backend.extraction.extractor import extract_graph  # Agent 2
    except ImportError:
        log.warning("backend.extraction not available yet; returning sources-only graph")
        return fallback_graph(query, mode, sources)
    out = extract_graph(query, mode, sources)
    return out if isinstance(out, GraphResult) else GraphResult.model_validate(out)


def run(inv: InvestigationResponse) -> InvestigationResponse:
    """Fill `inv` in place; never raises (errors land in inv.error / inv.status)."""
    try:
        inv.sources = retrieval.gather(inv.query, inv.mode)
        if not inv.sources:
            raise ResearchError("No sources found for this query. Try rephrasing it.")
        graph = _extract(inv.query, inv.mode, inv.sources)
        inv.nodes, inv.edges, inv.evidence, inv.assessments = (
            graph.nodes, graph.edges, graph.evidence, graph.assessments,
        )
        inv.status = "complete"
    except ResearchError as e:
        inv.status, inv.error = "failed", str(e)
    except ValidationError as e:
        inv.status, inv.error = "failed", f"Extraction returned malformed data: {e.error_count()} error(s)"
        log.exception("extraction output failed validation")
    except Exception as e:  # keep the server up and tell the frontend what happened
        inv.status, inv.error = "failed", f"{type(e).__name__}: {e}"
        log.exception("investigation failed")
    return inv
