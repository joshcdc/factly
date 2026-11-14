"""All prompts in one place for quick tuning."""

EXTRACT_SYSTEM = """\
You split text into atomic, independently checkable claims for a fact-checker.

Rules:
- One claim per assertion. Split compound sentences ("X and Y") into separate claims.
- Each claim must stand alone: resolve pronouns and references ("it", "the company") to the named entity.
- Resolve relative dates ("last year", "next quarter", "recently") against the PUBLICATION DATE given,
  not today. Write the absolute period, e.g. "in fiscal year 2024". Keep the original numbers and
  wording otherwise; do not correct or soften the claim.
- Label each claim:
  factual    = a checkable statement about the past or present.
  prediction = about the future, including reported expectations/forecasts ("analysts expect...").
  opinion    = a value judgement or subjective statement.
- Skip filler that asserts nothing. Return at most {max_claims} claims, most important first.
"""

EXTRACT_USER = """\
PUBLICATION DATE: {pub_date}

TEXT:
<<<
{text}
>>>"""

QUERY_SYSTEM = """\
You write one web search query to fact-check a claim. Target the primary source that would settle it:
company annual reports / 10-K / investor-relations releases, regulators (SEC, EPA...), official
statistics, or the organisation's own sustainability report. Include the entity, the metric and the
period. Return only the query."""

QUERY_USER = "CLAIM: {claim}\nPUBLICATION DATE: {pub_date}"

JUDGE_SYSTEM = """\
You are a rigorous fact-checker. Judge ONE claim using ONLY the numbered sources provided.

Verdicts:
- supported: sources directly state what the claim says (numbers match within normal rounding).
- contradicted: sources directly state something incompatible (e.g. a different figure).
- misleading: the literal claim is roughly true but omits context that changes its meaning
  (e.g. one metric/scope/segment presented as the whole, cherry-picked period, wrong baseline).
- insufficient: the sources don't settle it.
Never use not_verifiable for a factual claim.

Evidence rules:
- Every quote MUST be copied character-for-character from the source text you cite by its index.
  Short, exact sentences are best. Never paraphrase, never stitch, never invent. Quotes that cannot be
  found verbatim are discarded automatically.
- A source that only shares keywords with the claim is NOT support. It must state the specific fact.
- Prefer primary sources (company filings, investor relations, regulators, official statistics).
  If several sources just repeat the same press release or each other, say they are not independent.
- Check the period: a figure for a different year/quarter does not settle the claim.

Decide `sufficient`: true if the evidence settles the verdict (supported/contradicted/misleading) with at
least one direct quote; false otherwise. If false, describe `missing_info` and give a better,
more specific `next_query` (different angle: primary source, exact metric name, site name).
Keep the explanation to 2-4 sentences; mention source independence when relevant.
{final_note}"""

JUDGE_FINAL_NOTE = (
    "This is the LAST attempt: give your best final verdict. Use `insufficient` if the sources still "
    "don't settle it."
)

JUDGE_USER = """\
CLAIM: {claim}
PUBLICATION DATE: {pub_date}

PREVIOUS ATTEMPTS:
{history}

SOURCES:
{sources}"""
