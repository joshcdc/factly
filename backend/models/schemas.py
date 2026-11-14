"""Shared data contract (AGENT.md sections 3 and 4). All three workstreams import from here.

Additive fields beyond AGENT.md, so the frontend can poll: InvestigationResponse.status, .stage, .error.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .source import Source, SourceType

NodeType = Literal["person", "company", "location", "event", "concept", "claim", "source"]
Stance = Literal["supports", "contradicts", "neutral"]
ClaimStatus = Literal["supported", "partially_supported", "contradicted", "insufficient_evidence"]
Status = Literal["running", "complete", "failed"]


class Node(BaseModel):
    id: str
    type: NodeType
    label: str
    description: str = ""
    properties: dict = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)


class Edge(BaseModel):
    id: str
    source: str  # node id
    target: str  # node id
    relationship: str
    weight: float = Field(0.5, ge=0, le=1)  # display priority 0-1 (thickness, fade, detail slider); set by Agent 2
    stance: Stance | None = None  # set when the edge links evidence to a claim: supports / contradicts / neutral
    description: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    claim_id: str
    source_id: str
    stance: Stance
    excerpt: str
    reasoning: str = ""
    strength: int = Field(3, ge=1, le=5)


class ClaimAssessment(BaseModel):
    claim_id: str
    status: ClaimStatus
    confidence: float = Field(ge=0, le=1)  # model-assessed indicator, not a calibrated probability
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    explanation: str = ""


class GraphResult(BaseModel):
    """What Agent 2's extraction returns to the orchestrator."""

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    assessments: list[ClaimAssessment] = Field(default_factory=list)


class InvestigateRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class InvestigationResponse(GraphResult):
    investigation_id: str
    query: str
    status: Status = "running"
    stage: str | None = None  # while running: "searching" | "extracting" | "classifying" | "assessing"
    error: str | None = None
    sources: list[Source] = Field(default_factory=list)


__all__ = [
    "ClaimAssessment", "ClaimStatus", "Edge", "Evidence", "GraphResult", "InvestigateRequest",
    "InvestigationResponse", "Node", "NodeType", "Source", "SourceType", "Stance", "Status",
]
