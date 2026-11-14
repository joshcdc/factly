"""Orchestrates one investigation: research (Agent 1) -> backend.intelligence.analyse (Agent 2) -> response."""

import logging

from pydantic import ValidationError

from backend.intelligence import analyse
from backend.models.schemas import InvestigationResponse
from backend.research import retrieval
from backend.research.linkup import ResearchError

log = logging.getLogger("fakta.pipeline")


def run(inv: InvestigationResponse) -> InvestigationResponse:
    """Fill `inv` in place; never raises (errors land in inv.error / inv.status)."""

    def stage(name: str) -> None:
        inv.stage = name
        log.info("%s: %s", inv.investigation_id, name)

    try:
        stage("searching")
        inv.sources = retrieval.gather(inv.query)
        if not inv.sources:
            raise ResearchError("No sources found for this claim. Try rephrasing it.")
        graph = analyse(inv.query, inv.sources, on_progress=stage)  # also sets credibility_score on inv.sources
        inv.nodes, inv.edges, inv.evidence, inv.assessments = (
            graph.nodes, graph.edges, graph.evidence, graph.assessments,
        )
        inv.status = "complete"
    except ResearchError as e:
        inv.status, inv.error = "failed", str(e)
    except ValidationError as e:
        inv.status, inv.error = "failed", f"Analysis returned malformed data: {e.error_count()} error(s)"
        log.exception("analysis output failed validation")
    except Exception as e:  # keep the server up and tell the frontend what happened
        inv.status, inv.error = "failed", f"{type(e).__name__}: {e}"
        log.exception("investigation failed")
    inv.stage = None
    return inv
