"""Offline API tests (Agent 1): Linkup and analyse() stubbed, no keys needed.  Run: python -m tests.test_api"""

import os

from fastapi.testclient import TestClient

for _k in ("LINKUP_API_KEY", "ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"):
    os.environ.setdefault(_k, "test-key")  # pipeline.run checks that keys exist; nothing here calls a real service

from backend import pipeline
from backend.main import app
from backend.models.schemas import GraphResult, Node
from backend.research import linkup

CLAIM = "Microsoft controls OpenAI"
PAGES = {
    CLAIM: [
        {"title": "CMA decision", "url": "https://www.gov.uk/cma/openai", "content": "x" * 2000,
         "published_at": "2024-03-05T00:00:00"},
        {"title": "Dup", "url": "https://gov.uk/cma/openai/", "content": "dup", "published_at": None},
    ],
    f"fact check: {CLAIM}": [
        {"title": "Reuters &#x27;x&#x27;", "url": "https://www.reuters.com/a", "content": "short", "published_at": None},
    ],
}
fetched, stages = [], []


TRUSTED = [{"title": "AP", "url": "https://apnews.com/x", "content": "y" * 2000, "published_at": None}]


def fake_search(q, depth="standard", max_results=8, timeout=45, include_domains=None):
    if include_domains:
        assert "sec.gov" in include_domains
        return [dict(r) for r in TRUSTED]
    if q.endswith("official statement"):
        raise linkup.ResearchError("Linkup search timed out.")  # one failing query must not sink the rest
    return [dict(r) for r in PAGES.get(q, [])]


def fake_fetch(url, timeout=20):
    fetched.append(url)
    return "Full page text &amp; more " * 100


def fake_analyse(query, sources, on_progress=None):
    for st in ("extracting", "classifying", "assessing"):
        on_progress(st)
    for s in sources:
        s.credibility_score = 4  # Agent 2 sets this in place; the response must carry it
    return GraphResult(nodes=[Node(id="claim_1", type="claim", label=query)])


linkup.search, linkup.fetch, pipeline.analyse = fake_search, fake_fetch, fake_analyse
log_stage = pipeline.log.info
pipeline.log.info = lambda fmt, inv_id, st: stages.append(st)
client = TestClient(app)

# Async: POST returns running, the background task completes, GET returns the result.
r = client.post("/api/investigate", json={"query": CLAIM})
assert r.status_code == 200 and r.json()["status"] == "running" and r.json()["stage"] == "searching", r.json()
inv = client.get(f"/api/investigate/{r.json()['investigation_id']}").json()
assert inv["status"] == "complete" and inv["stage"] is None, inv
assert stages == ["searching", "extracting", "classifying", "assessing"], stages
srcs = inv["sources"]
# trusted-domain hit first, then the open web; duplicates removed
assert [s["url"] for s in srcs] == ["https://apnews.com/x", "https://www.gov.uk/cma/openai", "https://www.reuters.com/a"], srcs
assert srcs[1]["id"] == "source_2" and srcs[1]["source_type"] == "government" and srcs[1]["published_at"] == "2024-03-05"
assert srcs[2]["source_type"] == "news" and srcs[2]["content"].startswith("Full page text & more"), srcs[2]  # fetched
assert srcs[2]["title"] == "Reuters 'x'"
assert fetched == ["https://www.reuters.com/a"]  # only the thin passage was fetched
assert all(s["credibility_score"] == 4 for s in srcs)
assert inv["nodes"] == [{"id": "claim_1", "type": "claim", "label": CLAIM, "description": "", "properties": {},
                         "source_ids": []}]

# All searches fail -> failed status with a readable reason, not a 500.
linkup.search = lambda *a, **k: (_ for _ in ()).throw(linkup.ResearchError("Linkup account is out of credits."))
r = client.post("/api/investigate?wait=true", json={"query": "anything at all"}).json()
assert r["status"] == "failed" and r["error"] == "Linkup account is out of credits.", r

# Validation and 404.
assert client.post("/api/investigate", json={"query": ""}).status_code == 422
assert client.get("/api/investigate/nope").status_code == 404

# analyse() returning malformed data -> failed with a clear error, sources kept.
linkup.search = fake_search
pipeline.analyse = lambda q, s, on_progress=None: GraphResult.model_validate(
    {"nodes": [{"id": "n1", "type": "spaceship", "label": "x"}]})
r = client.post("/api/investigate?wait=true", json={"query": CLAIM}).json()
assert r["status"] == "failed" and "malformed" in r["error"] and r["sources"], r

print("API tests passed")
