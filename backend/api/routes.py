"""HTTP API. Investigations run in the background; the frontend polls GET."""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend import keys, pipeline
from backend.models.schemas import InvestigateRequest, InvestigationResponse

router = APIRouter(prefix="/api")

# shortcut: in-memory, lost on restart and per-process; move to a JSON file/DB if investigations must persist
INVESTIGATIONS: dict[str, InvestigationResponse] = {}


@router.get("/health")
def health() -> dict:
    return {"ok": True, "missing_keys": keys.missing_keys()}  # names only, never values


@router.post("/investigate", response_model=InvestigationResponse)
def investigate(req: InvestigateRequest, background: BackgroundTasks, wait: bool = False) -> InvestigationResponse:
    """Start an investigation. Returns status="running" at once; poll GET /api/investigate/{id}.

    `?wait=true` blocks until done (handy for curl and tests).
    """
    inv = InvestigationResponse(
        investigation_id=f"inv_{uuid.uuid4().hex[:10]}", query=req.query.strip(), stage="searching"
    )
    INVESTIGATIONS[inv.investigation_id] = inv
    if wait:
        return pipeline.run(inv)
    background.add_task(pipeline.run, inv)
    return inv.model_copy()


@router.get("/investigate/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(investigation_id: str) -> InvestigationResponse:
    inv = INVESTIGATIONS.get(investigation_id)
    if inv is None:
        raise HTTPException(404, f"No investigation {investigation_id}")
    return inv
