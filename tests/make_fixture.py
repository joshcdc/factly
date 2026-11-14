"""Regenerate fixtures/sample_investigation.json by running the real pipeline (Haiku + Jev) on made-up sources.

Run: python -m tests.make_fixture      (needs ANTHROPIC_API_KEY and TYPESAFE_API_KEY in .env)

The sources are illustrative, fictional articles on .example domains, not real publications.
"""

import json
from pathlib import Path

from backend.intelligence import analyse
from backend.models.schemas import InvestigationResponse
from backend.models.source import Source

QUERY = "Microsoft controls OpenAI"

SOURCES = [
    Source(id="source_1", url="https://dailytech.example/microsoft-openai-deal", title="Microsoft and OpenAI rework partnership",
           publisher="dailytech.example", published_at="2025-10-28", source_type="news", relevance_score=5,
           content=("Microsoft has invested roughly $13 billion in OpenAI since 2019. Under the restructured agreement, "
                    "Microsoft holds a stake of about 27% in OpenAI Group PBC. The OpenAI Foundation, a nonprofit, retains "
                    "control of the company and appoints its board. Satya Nadella, chief executive of Microsoft, said the "
                    "partnership remains strong.")),
    Source(id="source_2", url="https://filings.example/openai-pbc", title="OpenAI Group PBC: governance summary",
           publisher="filings.example", published_at="2025-11-02", source_type="government", relevance_score=5,
           content=("OpenAI Group PBC is a public benefit corporation. The OpenAI Foundation holds the power to appoint all "
                    "members of the board of directors of OpenAI Group PBC. Microsoft, OpenAI's largest outside investor, "
                    "does not have a board seat and does not control OpenAI. Sam Altman is chief executive of OpenAI.")),
    Source(id="source_3", url="https://techblog.example/who-runs-openai", title="Opinion: Microsoft is really in charge",
           publisher="techblog.example", published_at="2025-11-05", source_type="web", relevance_score=3,
           content=("OpenAI depends on Microsoft's Azure cloud for most of its computing power. Critics argue that Microsoft "
                    "has effective control over OpenAI's strategy because of this dependence. Microsoft has exclusive rights "
                    "to sell OpenAI models through Azure until 2032.")),
    Source(id="source_4", url="https://marketwatch.example/azure-revenue", title="Azure growth beats estimates",
           publisher="marketwatch.example", published_at="2025-10-29", source_type="news", relevance_score=2,
           content="Microsoft reported quarterly revenue of $77.7 billion. Azure revenue grew 40%, led by AI services."),
]


def main() -> None:
    result = analyse(QUERY, SOURCES, on_progress=lambda s: print("..", s))
    resp = InvestigationResponse(investigation_id="investigation_sample", query=QUERY, status="complete",
                                 sources=SOURCES, **result.model_dump())
    InvestigationResponse.model_validate_json(resp.model_dump_json())  # round-trip check against the contract
    out = Path(__file__).resolve().parent.parent / "fixtures" / "sample_investigation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(resp.model_dump_json(indent=2), encoding="utf-8")
    a = resp.assessments[0]
    print(f"wrote {out}: {len(resp.nodes)} nodes, {len(resp.edges)} edges, {len(resp.evidence)} evidence; "
          f"{a.status} ({a.confidence})")


if __name__ == "__main__":
    main()
