# Backend: research and API (Agent 1)

FastAPI server that takes a topic or claim, researches it with Linkup and returns graph data in the shared contract (`backend/models/schemas.py`).

## Run

From the repo root:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
echo "LINKUP_API_KEY=..." >> .env          # .env is gitignored
uvicorn backend.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/investigate` | Body `{"query": "...", "mode": "topic" \| "claim"}`. Returns immediately with `status: "running"`. |
| `GET` | `/api/investigate/{investigation_id}` | Poll until `status` is `"complete"` or `"failed"` (then read `error`). |
| `POST` | `/api/investigate?wait=true` | Same as POST, but waits for the result. Handy for curl and tests. |
| `GET` | `/api/health` | `{"ok": true}` |

The response is `InvestigationResponse`: the AGENT.md shape (`investigation_id, query, nodes, edges, sources, evidence, assessments`) plus `mode`, `status` and `error`.

```bash
curl -s -X POST 'localhost:8000/api/investigate?wait=true' \
  -H 'content-type: application/json' \
  -d '{"query": "Microsoft owns 49% of OpenAI", "mode": "claim"}'
```

**Frontend (Agent 3):** POST, then poll GET about once a second. A typical research run takes 3 to 6 seconds. Extraction will add more once Agent 2's module is connected. CORS is open for local development.

## What research does

1. Runs 3 Linkup searches in parallel (`output_type="searchResults"`, depth `standard`):
   - **topic:** the query, plus "official announcement" and "latest news" variants
   - **claim:** the query, plus "fact check:" and "official statement" variants
2. Interleaves the results so each search's best hits come first, de-duplicates by URL and keeps the top 12.
3. For results whose passage is under 1,500 characters, fetches the full page with Linkup `fetch`.
4. Normalises each result into a `Source`:
   - cleaned text: HTML entities decoded, markdown links and emphasis removed
   - `publisher` is the domain name
   - `source_type` is one of news, government, company, academic, reference, social or web
   - `relevance_score` runs from 5 down to 1 by search rank
   - `credibility_score` is left `null` for Agent 2's source ranking
5. If one search fails, the others continue. If all of them fail, `status` is `"failed"` with a readable reason, such as "Linkup account is out of credits."

## Handoff to Agent 2

Create `backend/extraction/extractor.py` with:

```python
from backend.models.schemas import GraphResult, Source

def extract_graph(query: str, mode: str, sources: list[Source]) -> GraphResult:  # or an equivalent dict
    ...
```

The orchestrator (`backend/pipeline.py`) calls it automatically once the module exists and validates its output against the contract. Malformed output turns into `status: "failed"` with a clear error, and the sources are kept.

Until the module exists, the API returns a simple graph: one query node (type `claim` or `concept`), one `source` node per source, and `discusses` edges between them. That gives the frontend real data to build against now.

## Test

```bash
python -m backend.tests.test_api                                       # offline, Linkup stubbed
python -m backend.research.retrieval "Microsoft controls OpenAI" --claim   # one live retrieval
```

`in-memory` store: investigations are lost on restart, which is fine for the demo (AGENT.md: no database unless necessary).
