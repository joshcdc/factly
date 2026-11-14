"""Offline API tests: Linkup is stubbed, no keys needed.  Run: python -m backend.tests.test_api"""

from fastapi.testclient import TestClient

from backend.main import app
from backend.research import linkup

PAGES = {
    "Microsoft controls OpenAI": [
        {"title": "CMA decision", "url": "https://www.gov.uk/cma/openai", "content": "x" * 2000, "published_at": "2024-03-05T00:00:00"},
        {"title": "Dup", "url": "https://gov.uk/cma/openai/", "content": "dup", "published_at": None},
    ],
    "fact check: Microsoft controls OpenAI": [
        {"title": "Reuters &#x27;x&#x27;", "url": "https://www.reuters.com/a", "content": "short", "published_at": None},
    ],
}
fetched = []


def fake_search(q, depth="standard", max_results=8, timeout=45):
    if q.endswith("official statement"):
        raise linkup.ResearchError("Linkup search timed out.")  # one failing query must not sink the rest
    return [dict(r) for r in PAGES.get(q, [])]


def fake_fetch(url, timeout=20):
    fetched.append(url)
    return "Full page text &amp; more " * 100


linkup.search, linkup.fetch = fake_search, fake_fetch
client = TestClient(app)

# Claim mode, async: POST returns running, the background task completes, GET returns the result.
r = client.post("/api/investigate", json={"query": "Microsoft controls OpenAI", "mode": "claim"})
assert r.status_code == 200 and r.json()["status"] == "running", r.json()
inv = client.get(f"/api/investigate/{r.json()['investigation_id']}").json()
assert inv["status"] == "complete", inv
srcs = inv["sources"]
assert [s["url"] for s in srcs] == ["https://www.gov.uk/cma/openai", "https://www.reuters.com/a"], srcs  # deduped, interleaved
assert srcs[0]["id"] == "source_1" and srcs[0]["source_type"] == "government" and srcs[0]["published_at"] == "2024-03-05"
assert srcs[1]["source_type"] == "news" and srcs[1]["content"].startswith("Full page text & more"), srcs[1]  # fetched + cleaned
assert srcs[1]["title"] == "Reuters 'x'"
assert fetched == ["https://www.reuters.com/a"]  # only the thin passage was fetched
node_types = {n["id"]: n["type"] for n in inv["nodes"]}
assert node_types == {"query_1": "claim", "source_1": "source", "source_2": "source"}, node_types
assert all(e["target"] == "query_1" for e in inv["edges"]) and len(inv["edges"]) == 2

# All searches fail -> failed status with a readable reason, not a 500.
linkup.search = lambda *a, **k: (_ for _ in ()).throw(linkup.ResearchError("Linkup account is out of credits."))
r = client.post("/api/investigate?wait=true", json={"query": "anything at all", "mode": "topic"}).json()
assert r["status"] == "failed" and r["error"] == "Linkup account is out of credits.", r

# Validation and 404.
assert client.post("/api/investigate", json={"query": "", "mode": "topic"}).status_code == 422
assert client.post("/api/investigate", json={"query": "abc def", "mode": "other"}).status_code == 422
assert client.get("/api/investigate/nope").status_code == 404

# Agent 2 returning malformed data -> failed with a clear error, sources kept.
import sys, types  # noqa: E401,E402
linkup.search = fake_search
bad = types.ModuleType("backend.extraction.extractor")
bad.extract_graph = lambda q, m, s: {"nodes": [{"id": "n1", "type": "spaceship", "label": "x"}]}
sys.modules["backend.extraction"] = types.ModuleType("backend.extraction")
sys.modules["backend.extraction.extractor"] = bad
r = client.post("/api/investigate?wait=true", json={"query": "Microsoft controls OpenAI", "mode": "claim"}).json()
assert r["status"] == "failed" and "malformed" in r["error"] and r["sources"], r

print("backend API tests passed")
