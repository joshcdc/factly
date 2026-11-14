# Backend: research and API (Agent 1)

FastAPI server that takes a claim, researches it with Linkup, hands the sources to Agent 2 (`backend.intelligence.analyse`) and returns graph data in the shared contract (`backend/models/schemas.py`).

## Run

From the repo root:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# .env (gitignored) needs: LINKUP_API_KEY, ANTHROPIC_API_KEY, TYPESAFE_API_KEY (Jev)
uvicorn backend.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/investigate` | Body `{"query": "<claim>"}`. Returns immediately with `status: "running"`. |
| `GET` | `/api/investigate/{investigation_id}` | Poll until `status` is `"complete"` or `"failed"` (then read `error`). |
| `POST` | `/api/investigate?wait=true` | Same as POST, but waits for the result. Handy for curl and tests. |
| `GET` | `/api/health` | `{"ok": true}` |

The response is `InvestigationResponse`: the AGENT.md shape (`investigation_id, query, nodes, edges, sources, evidence, assessments`) plus `status` (`running`/`complete`/`failed`), `stage` (while running: `searching`, `extracting`, `classifying`, `assessing`) and `error`.

```bash
curl -s -X POST 'localhost:8000/api/investigate?wait=true' \
  -H 'content-type: application/json' \
  -d '{"query": "Microsoft owns 49% of OpenAI"}'
```

**Frontend (Agent 3):** POST, then poll GET about once a second. A full run takes about 20 seconds: about 3 for research, then extraction and stance classification. Show `stage` as the loading message. CORS is open for local development.

## What research does

1. Runs 3 Linkup searches in parallel (`output_type="searchResults"`, depth `standard`): the claim as written, plus "fact check:" and "official statement" variants, so sources both for and against the claim turn up.
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

`backend/pipeline.py` calls `backend.intelligence.analyse(query, sources, on_progress)` (AGENT.md, "Agent 1 → Agent 2 hand-off"). `on_progress` updates `stage`. `analyse` sets `credibility_score` on the sources in place. Its output is validated against the contract; malformed output turns into `status: "failed"` with a clear error, and the sources are kept.

## Test

```bash
python -m tests.test_api                                     # offline, Linkup and analyse() stubbed
python -m backend.research.retrieval "Microsoft controls OpenAI"   # one live retrieval
```

`in-memory` store: investigations are lost on restart, which is fine for the demo (AGENT.md: no database unless necessary).
