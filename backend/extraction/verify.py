"""Check that a quote really appears in the source text (normalised exact match, then strict fuzzy)."""

import re
import unicodedata
from difflib import SequenceMatcher

MIN_WORDS = 5
FUZZY = 0.92
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_NEG = re.compile(r"\b(?:not|no|never|none|nor|without)\b|n't")
_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " "})


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_PUNCT).lower()
    return re.sub(r"\s+", " ", s).strip(" \"'.")


_SENT = re.compile(r"(?<=[.!?])\s+")


def context_for(quote: str, source_text: str, around: int = 2, max_chars: int = 1500) -> str:
    """The sentences just before and after the quote in the original text, so pronouns can be resolved."""
    sents = [s for s in _SENT.split(source_text) if s.strip()]
    head = normalise(quote)[:40]
    for i, s in enumerate(sents):
        if head and head in normalise(" ".join(sents[i : i + 3])):
            if head not in normalise(s) and i + 1 < len(sents):
                continue  # the quote starts in a later sentence of this window
            return " ".join(sents[max(0, i - around) : i + 1 + around + quote.count(". ")])[:max_chars]
    return ""


def verify_quote(quote: str, source_text: str) -> bool:
    q, src = normalise(quote), normalise(source_text)
    if len(q.split()) < MIN_WORDS or "..." in q or "…" in q:
        return False
    i = src.find(q)
    if i >= 0:
        # a number must not be a prefix of a longer number ("97.6" inside "97.69")
        end = i + len(q)
        return not (q[-1].isdigit() and end < len(src) and src[end].isdigit())
    # fuzzy: tolerate small punctuation/typo noise, never different numbers or negation
    a, _, size = SequenceMatcher(None, src, q, autojunk=False).find_longest_match(0, len(src), 0, len(q))
    if size < min(20, len(q) // 3):
        return False
    lo, hi = max(0, a - len(q)), min(len(src), a + 2 * len(q))
    best = max(
        (src[j : j + len(q)] for j in range(lo, max(lo + 1, hi - len(q) + 1))),
        key=lambda w: SequenceMatcher(None, w, q, autojunk=False).ratio(),
    )
    return (
        SequenceMatcher(None, best, q, autojunk=False).ratio() >= FUZZY
        and _NUM.findall(best) == _NUM.findall(q)
        and _NEG.findall(best) == _NEG.findall(q)
    )
