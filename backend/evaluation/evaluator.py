"""Claim status and confidence from classified evidence. Plain rules, no model."""

from backend.models.schemas import ClaimAssessment, Evidence
from backend.models.source import Source

MIN_TOTAL = 0.2  # below this total weight there is too little signal to say anything


def assess(claim_id: str, evidence: list[Evidence], sources: list[Source]) -> ClaimAssessment:
    cred = {s.id: s.credibility_score or 2 for s in sources}
    pub = {s.id: s.publisher for s in sources}

    def side(stance):
        items = [e for e in evidence if e.stance == stance]
        best = {}  # one vote per publisher: repeated articles are not independent
        for e in items:
            w = (e.strength / 5) * (cred.get(e.source_id, 2) / 5)
            p = pub.get(e.source_id, e.source_id)
            best[p] = max(best.get(p, 0), w)
        top_cred = max((cred.get(e.source_id, 2) for e in items), default=0)
        return sum(best.values()), len(best), top_cred

    sup, n_sup, c_sup = side("supports")
    con, n_con, c_con = side("contradicts")
    total = sup + con
    ratio = sup / total if total else 0.5

    if total < MIN_TOTAL:
        status = "insufficient_evidence"
    elif ratio >= 0.8 and (n_sup >= 2 or c_sup >= 5):
        status = "supported"
    elif ratio <= 0.2 and (n_con >= 2 or c_con >= 5):
        status = "contradicted"
    elif 0.2 < ratio < 0.8:
        status = "partially_supported"
    else:
        status = "insufficient_evidence"  # one-sided but from a single non-authoritative source

    decisive = status in ("supported", "contradicted")
    confidence = round(max(ratio, 1 - ratio) * min(1, total / 1.5), 2) if decisive else round(min(1, total / 3), 2)
    names = {"supported": "supports", "contradicted": "contradicts"}
    explanation = (
        f"{n_sup} independent source(s) support and {n_con} contradict the claim "
        f"(weighted {sup:.2f} vs {con:.2f})."
        + ("" if status != "insufficient_evidence" else " Not enough credible, independent evidence to decide.")
    )
    return ClaimAssessment(
        claim_id=claim_id,
        status=status,
        confidence=confidence,
        supporting_evidence=[e.id for e in evidence if e.stance == "supports"],
        contradicting_evidence=[e.id for e in evidence if e.stance == "contradicts"],
        explanation=explanation,
    )
