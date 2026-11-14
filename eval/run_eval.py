"""Run the pipeline over eval/claims.csv and report accuracy + confusion table.

Usage:
  python -m eval.run_eval              # uses cached reports where available
  python -m eval.run_eval --fresh      # ignore the cache, re-run everything
  python -m eval.run_eval --limit 5 --workers 4
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from veritas import cache, pipeline
from veritas.schema import VERDICTS, Report

HERE = Path(__file__).resolve().parent


def row_verdict(report: Report) -> str:
    """One verdict per eval row, even if extraction split the text into several claims."""
    vs = [c.verdict for c in report.claims if c.verdict]
    if not vs:
        return "insufficient"
    for v in ("contradicted", "misleading"):
        if v in vs:
            return v
    if all(v == "not_verifiable" for v in vs):
        return "not_verifiable"
    factual = [v for v in vs if v != "not_verifiable"]
    return "supported" if all(v == "supported" for v in factual) else "insufficient"


def evaluate_row(row: dict, fresh: bool) -> dict:
    pub = row.get("pub_date") or None
    report = None if fresh else cache.get(row["text"], pub)
    try:
        report = report or pipeline.run(row["text"], pub)
        got = row_verdict(report)
        err = None
    except Exception as e:
        got, err = "error", f"{type(e).__name__}: {e}"
    return {
        **row,
        "got": got,
        "error": err,
        "claims": [c.model_dump() for c in report.claims] if report else [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(HERE / "claims.csv"))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, newline="")))[: args.limit]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda r: evaluate_row(r, args.fresh), rows))

    for r in results:
        ok = "✓" if r["got"] == r["expected_verdict"] else "✗"
        print(f"{ok} expected={r['expected_verdict']:<14} got={r['got']:<14} {r['text'][:70]}")
        if r["error"]:
            print(f"    error: {r['error']}")

    n = len(results)
    correct = sum(r["got"] == r["expected_verdict"] for r in results)
    print(f"\nOverall accuracy: {correct}/{n} = {correct / max(1, n):.0%}\n")

    print("Per expected verdict (recall):")
    for v in VERDICTS:
        sub = [r for r in results if r["expected_verdict"] == v]
        if sub:
            k = sum(r["got"] == v for r in sub)
            print(f"  {v:<15} {k}/{len(sub)} = {k / len(sub):.0%}")

    cols = list(VERDICTS) + (["error"] if any(r["got"] == "error" for r in results) else [])
    abbrev = {"supported": "sup", "contradicted": "con", "misleading": "mis", "insufficient": "ins",
              "not_verifiable": "n/v", "error": "err"}
    print("\nConfusion (rows = expected, cols = got):")
    print(" " * 16 + "".join(f"{abbrev[c]:>6}" for c in cols))
    for v in VERDICTS:
        sub = [r for r in results if r["expected_verdict"] == v]
        if sub:
            print(f"  {v:<14}" + "".join(f"{sum(r['got'] == c for r in sub):>6}" for c in cols))

    out = HERE / "results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()
