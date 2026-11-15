# factly

**Fact-check a claim and see the network of people, organisations and sources behind it.**

Type a claim. factly searches the web, reads the sources, checks every quote against the page it came from, and returns a
verdict with a confidence level, plus an interactive graph of the entities involved and how they connect. Click anything
in the graph to see who said what, and open the original sources.

> A working prototype, not a production service: see [Known limitations](#known-limitations).

---

## Features

**Verdict you can inspect**
- Four verdicts: *supported*, *partially supported*, *contradicted*, *insufficient evidence*.
- A confidence level (low / medium / high, with a 0-1 score) that rises with the amount of independent, credible evidence
  and never reaches 1. It measures how well-founded the verdict is, **not** the probability that the claim is true.
- Every supporting or contradicting quote is shown with its source, and each quote is **verified against the page text**:
  a quote that does not appear in the source is dropped.

**Evidence handling**
- Stance (supports / contradicts / neutral) is decided by a classifier (TypeSafe Jev), not by the language model.
- A quote only counts if the entities named in the claim appear in it or in its surrounding sentences; Jev also sees those sentences to resolve "it" and "the company".
- Sources are weighted by credibility (rules by domain and type, refined by Jev, 1-5). One publisher counts once, however many pages it has.
- Official sources (filings, regulators, an organisation's own announcement) carry extra weight.

**Knowledge graph**
- Entities (people, companies, locations, events, concepts) and the relationships between them, extracted per source.
- Duplicates are merged ("Microsoft" and "Microsoft Corp.", "Altman" and "Sam Altman", accents and typos handled), with Jev settling
  ambiguous cases. A parent and its subsidiary stay separate.
- Reported or disputed relationships are labelled `alleged …` and never stated as fact; opinions are never turned into relationships.
- Each entity has a short summary written from what the sources said, how many sources and publishers mention it, and its connections.
- The graph is kept readable: at most 12 entities, and none is left unconnected.

**Interface**
- Interactive force-directed graph: drag nodes, pan, zoom, and a **Recentre** button that glides back to the claim.
- The claim node is coloured by its verdict; node shapes and colours show entity types, with a legend.
- Details panel: verdict card with confidence and counts, entity summaries, connected entities, and a sources list with the supporting quotes.
- Clear error messages for missing or rejected API keys, an empty search, and out-of-credit accounts.

---

## How it works

```
 claim
   |
   v
 1. Research       Linkup web search (open web + trusted domains), de-duplicated, full pages fetched when a passage is thin   -> up to 12 sources
   |
   v
 2. Analysis       keep the best 10 sources (max 2 per publisher), rate their credibility
   |               Claude Haiku reads each source: entities, relationships, candidate quotes
   |               verify every quote against the page text; merge duplicate entities
   |               Jev classifies each quote: supports / contradicts / neutral
   |               rules turn the evidence into a status and a confidence
   v
 3. Graph + API    nodes, edges, evidence, assessment, sources as one JSON response (the shared contract)
   |
   v
 4. Interface      React app: graph, verdict card, details panel
```

The language model only **extracts** (names, relationships, candidate quotes). It never judges truth. Stance comes from Jev,
and the verdict comes from plain, testable rules over the evidence.

**Confidence in short:** evidence mass with diminishing returns (`1 - exp(-mass / 2.5)`), times the winning side's share of the
evidence, times an authority factor, times a coverage factor. Official sources count 2.5x, and the score is capped at 0.95.
A lone official source reaches about 0.63; two reach about 0.86; two ordinary news sites about 0.47.

---

## APIs and models

| Service | Used for | Model | Code |
|---|---|---|---|
| **Linkup API** | Web search: three variants of the claim plus a search limited to trusted domains (regulators, wire services, major newsrooms). Fetches the full page when a search passage is under 1,500 characters. | none (search API) | `backend/research/` |
| **Anthropic API** (Messages, structured outputs) | Reading each source: entities, relationships and up to 3 candidate quotes. Also the short summary for each entity. | **Claude Haiku 5.5** (`claude-haiku-5-5`), low effort | `backend/extraction/` |
| **TypeSafe API** (System One) | The Jev classifier: the stance of each quote, source credibility (1-5), and whether two entity names are the same thing. | **Jev** (`jev-1.13.0`, pinned) | `backend/evaluation/jev.py` |

- The language model never judges truth. It extracts; Jev classifies, and the verdict comes from rules over the evidence.
- Jev answers are thresholded: a stance needs at least 60% probability (otherwise the quote counts as neutral), and two entities
  merge only at 90% or more.
- The extraction model is one constant (`MODEL` in `backend/extraction/extractor.py`), so it can be swapped for a larger Claude model.
- The backend itself is a REST API (below), built with FastAPI and Pydantic. The frontend is React, TypeScript and Vite, and calls
  no external services.

---

## Project layout

```
backend/
  main.py, api/            FastAPI app and routes (Linkup -> analysis -> response)
  research/                Linkup search and fetch, source normalisation
  extraction/              Claude extraction, quote verification, entity merging, prompts
  evaluation/              Jev (stance, credibility, entity matching), source ranking, verdict and confidence
  intelligence.py          analyse(): sources in, graph out
  models/                  the shared data contract (Pydantic): Source, Node, Edge, Evidence, assessment
  keys.py                  API key checks
frontend/                  React + TypeScript + Vite app
fixtures/                  sample investigation used by the frontend's mock mode and tests
tests/                     offline test suites
graph-engine/              reference copy of the original force-layout engine (not used at runtime)
AGENT.md                   the original plan, the workstreams and the data contract in full
```

---

## Setup

You need **Python 3.11+**, **Node 22**, and three API keys.

| Variable | Used for |
|---|---|
| `LINKUP_API_KEY` | web search (Linkup) |
| `ANTHROPIC_API_KEY` | reading sources and writing entity summaries (Claude Haiku 5.5) |
| `TYPESAFE_API_KEY` | Jev: stance, credibility and entity matching ([TypeSafe](https://typesafe.ai)) |

```bash
# 1. Backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env.  Then fill in the three keys; .env is gitignored
uvicorn backend.main:app --reload --port 8000

# 2. Frontend (a second terminal)
cd frontend
npm install
# create the file frontend/.env containing the single line:  VITE_USE_MOCK=false
# (without it the UI shows built-in sample data instead of calling the backend)
npm run dev                       # http://localhost:5173  (it proxies /api to port 8000)
```

Open http://localhost:5173, type a claim and press **Investigate**. A run takes about 12-20 seconds and spends a few Linkup credits.

To try the interface with no keys and no backend, leave out `VITE_USE_MOCK=false`: it then shows a sample graph, and `?fake=60` in the
URL shows a random 60-node graph for testing density and performance.

If a key is missing or rejected, the app says which one. `GET /api/health` also lists any missing keys by name.

**Behind a proxy or antivirus that inspects HTTPS?** `pip` and `npm` may fail with a certificate error. Use the system certificate store instead of
turning verification off: `pip install --use-feature=truststore -r requirements.txt` (after `pip install truststore`) and
`NODE_OPTIONS=--use-system-ca npm install`.

---

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/investigate` | body `{"query": "<claim>"}`; returns at once with `status: "running"` |
| `GET` | `/api/investigate/{id}` | poll until `status` is `complete` or `failed` (then read `error`) |
| `POST` | `/api/investigate?wait=true` | same as POST, but waits for the result (handy for curl) |
| `GET` | `/api/health` | `{"ok": true, "missing_keys": []}` |

The response holds `nodes`, `edges`, `evidence`, `assessments` and `sources`, plus `status`, `stage` and `error`. Entity nodes carry a
`summary` and source and publisher counts; source-to-claim edges carry a `stance`. The full
schema is in `backend/models/schemas.py`, and `AGENT.md` explains each field.

---

## Tests

All suites run offline: no keys and no network.

```bash
python -m tests.test_keys          # missing / rejected key messages
python -m tests.test_api           # API and pipeline, with search and analysis stubbed
python -m tests.test_intelligence  # extraction, merging, graph building, summaries
python -m tests.test_merge         # entity merging rules
python -m tests.test_evaluation    # source ranking, stance guard, verdict and confidence
```

`python -m tests.make_fixture` regenerates `fixtures/sample_investigation.json` through the real pipeline (this one needs the keys).

---

## Known limitations

- **Verdicts depend on the sources found.** A claim with few or one-sided sources gets a low-confidence or *insufficient evidence* result.
  Independence is counted by publisher, so several outlets repeating one report still count as several.
- **Confidence is not a probability.** It reflects how much credible evidence there is and how much it agrees.
- **Reported beliefs can count as support.** An article saying "he argues the Earth is flat" can be classified as supporting the claim,
  which lowers confidence on claims that proponents talk about. A fix is designed and tested but not applied yet.
- **Relationship edges are model-written** and are not verified against the page the way evidence quotes are (in testing, the two entities
  always appeared together in a cited source, but the relationship itself is not checked).
- **Opinions and predictions** are not detected; they come back as *insufficient evidence* rather than "not checkable".
- **Entity summaries are model-written** from what each source said and are not verified.
- **Claims about private individuals** will turn up allegations in news coverage. Do not use them for demos or commit their results.
- Prototype settings: investigations are held in memory and lost on restart, CORS is open for local development, and there is no
  authentication or rate limiting.
- Search costs Linkup credits on every run; a run needs all three keys and a funded Linkup account.
