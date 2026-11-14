"""Claim status and confidence from classified evidence. Plain rules, no model.

Status is decided from the weighted evidence on each side. Confidence is how well-founded that verdict is, not a
probability that the claim is true; it is built from evidence mass (with diminishing returns), agreement, authority and
coverage, and never reaches 1.
"""

import math

from backend.models.schemas import ClaimAssessment, Evidence
from backend.models.source import Source

MIN_TOTAL = 0.2  # below this total weight there is too little signal to say anything

MASS_K = 2.5  # evidence mass at which confidence reaches 1 - 1/e (63%); larger = slower to build confidence
OFFICIAL_CRED = 5  # an authoritative source: filing, regulator, the organisation's own announcement
OFFICIAL_MIN_STRENGTH = 4  # a tangential mention from an official site does not get the boost
OFFICIAL_BOOST = 2.5  # official evidence counts this many times in the evidence mass
# One source can add at most 2.5 mass, i.e. 1 - exp(-1) = 0.63 confidence, so a lone official source is naturally
# capped well below an agreed-on verdict (two official sources reach 0.86).
MAX_CONFIDENCE = 0.95
INSUFFICIENT_CAP = 0.3


def band(confidence: float) -> str:
    return "low" if confidence < 0.4 else "medium" if confidence <= 0.7 else "high"


def assess(claim_id: str, evidence: list[Evidence], sources: list[Source]) -> ClaimAssessment:
    cred = {s.id: s.credibility_score or 2 for s in sources}
    pub = {s.id: s.publisher for s in sources}
    analysed = len(set(pub.values())) or 1

    def side(stance):
        items = [e for e in evidence if e.stance == stance]
        best, boosted = {}, {}  # one vote per publisher: repeated articles are not independent
        official = False
        for e in items:
            c = cred.get(e.source_id, 2)
            w = (e.strength / 5) * (c / 5)
            is_official = c >= OFFICIAL_CRED and e.strength >= OFFICIAL_MIN_STRENGTH
            p = pub.get(e.source_id, e.source_id)
            best[p] = max(best.get(p, 0), w)
            boosted[p] = max(boosted.get(p, 0), w * (OFFICIAL_BOOST if is_official else 1))
            official = official or is_official
        top_cred = max((cred.get(e.source_id, 2) for e in items), default=0)
        return sum(best.values()), len(best), top_cred, sum(boosted.values()), official

    sup, n_sup, c_sup, mass_sup, off_sup = side("supports")
    con, n_con, c_con, mass_con, off_con = side("contradicts")
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

    relevant = len({pub.get(e.source_id, e.source_id) for e in evidence if e.stance != "neutral"})
    coverage = 0.7 + 0.3 * min(1, relevant / analysed)  # how many of the analysed sources said something about it

    if status in ("supported", "contradicted"):
        win_sup = status == "supported"
        mass, top, official = (mass_sup, c_sup, off_sup) if win_sup else (mass_con, c_con, off_con)
        base = 1 - math.exp(-mass / MASS_K)  # diminishing returns: more sources keep helping, less each time
        agreement = max(ratio, 1 - ratio)
        authority = 1.0 if top >= 4 else 0.8
        confidence = base * agreement * authority * (1.0 if official else coverage)  # official sources need no echo
    elif status == "partially_supported":
        base = 1 - math.exp(-(mass_sup + mass_con) / MASS_K)
        confidence = base * (1 - abs(ratio - 0.5)) * coverage  # how sure we are that the evidence really is mixed
    else:
        confidence = min(INSUFFICIENT_CAP, 1 - math.exp(-total / MASS_K))
    confidence = round(min(MAX_CONFIDENCE, confidence), 2)

    explanation = (
        f"{n_sup} independent source(s) support and {n_con} contradict the claim "
        f"(weighted {sup:.2f} vs {con:.2f})."
        + (" Not enough credible, independent evidence to decide." if status == "insufficient_evidence" else "")
        + f" Confidence: {band(confidence)}."
    )
    return ClaimAssessment(
        claim_id=claim_id,
        status=status,
        confidence=confidence,
        supporting_evidence=[e.id for e in evidence if e.stance == "supports"],
        contradicting_evidence=[e.id for e in evidence if e.stance == "contradicts"],
        explanation=explanation,
    )
