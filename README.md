# fakta.ai — Veritas, an autonomous fact-checking agent

Paste text (a news excerpt, a financial claim or an AI answer). Veritas:

1. **Extracts** atomic claims (pronouns and relative dates resolved against the publication date) and labels each as `factual`, `prediction` or `opinion`.
2. **Investigates** each factual claim. The LLM writes a targeted query, Linkup returns raw passages (`output_type="searchResults"`) and the LLM judges them. If the evidence is insufficient, it searches again with a sharper query (max 3 searches per claim; the last one uses `depth="deep"`).
3. **Reports** a verdict per claim (`supported`, `contradicted`, `misleading`, `insufficient` or `not_verifiable`) with an explanation, cited quotes and the agent's step-by-step trace.

**Core rule:** every quote is checked in code against the source text Linkup returned (`veritas/retrieve.py::verify_quote`). The check normalises whitespace, case and quote marks, then tries an exact substring match, then a `difflib` fuzzy match at ≥ 0.9. Numbers must match exactly even in fuzzy mode. Quotes that fail are dropped. If a claim has a decisive verdict but no verified quote, it is downgraded to `insufficient`.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -r requirements.txt
cp .env.example .env    # then fill in LINKUP_API_KEY and ANTHROPIC_API_KEY
```

| Variable | Default | Notes |
|---|---|---|
| `LINKUP_API_KEY` | – | required |
| `ANTHROPIC_API_KEY` | – | required |
| `LLM_MODEL` | `claude-opus-5-5` | any Claude model |
| `LLM_EFFORT` | `medium` | `low` is faster and cheaper; `high` is more careful |
| `LLM_FALLBACKS` | `default` | server-side refusal fallback; set it empty if your model doesn't support it |

## Run

```bash
streamlit run app.py
```

For the demo, run the showcase input once while online. The report is saved to `.cache/reports/`. Then turn on **"Load results from cache"** in the sidebar to replay it offline.

Each stage also runs from the command line:

```bash
python -m veritas.retrieve "Tesla 2024 annual revenue"         # one raw Linkup search
python -m veritas.extract                                       # claim extraction on the demo text
python -m veritas.investigate "Tesla is headquartered in Austin, Texas."
python -m veritas.pipeline                                      # full demo, printed
python -m tests.test_offline                                    # offline tests with stubbed Linkup and LLM (no keys needed)
```

## Eval

```bash
python -m eval.run_eval              # reuses cached reports when present
python -m eval.run_eval --fresh      # re-run everything
python -m eval.run_eval --limit 5
```

The runner prints overall accuracy, accuracy per expected verdict and a confusion table, and writes `eval/results.json`. `eval/claims.csv` has 21 starter claims: true facts, the same facts with altered numbers or wrong periods (expected `contradicted`), misleading ones (including an ESG scope case) and predictions or opinions. When extraction splits a row into several claims, they are combined into one row verdict (contradicted > misleading > supported only if all factual claims are supported).

## Layout

```
veritas/
  schema.py       Evidence, Step, Claim, Report (plus the LLM output models)
  prompts.py      every prompt, in one place for tuning
  llm.py          call_json(): Claude structured outputs → Pydantic, one retry on a validation error
  extract.py      extract_claims(text, pub_date)
  retrieve.py     search(query, depth), verify_quote(quote, source_text)
  investigate.py  investigate(claim, pub_date): the agent loop
  pipeline.py     run(text, pub_date): thread pool across claims (max 8), cached
  cache.py        JSON report cache keyed on a hash of (text, pub_date)
app.py            Streamlit UI
eval/             claims.csv, run_eval.py
tests/            offline end-to-end test
```

## Cost and latency

Each factual claim makes 1 query-writing call plus 1 to 3 judge calls, and 1 to 3 Linkup searches. Claims run in parallel. To speed up a live demo, set `LLM_EFFORT=low` or use a smaller `LLM_MODEL`.
