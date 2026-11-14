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


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_PUNCT).lower()
    return re.sub(r"\s+", " ", s).strip()


def normalise(s: str) -> str:
    return _fold(s).strip(" \"'.")


_SENT = re.compile(r"(?<=[.!?])\s+")


def context_for(quote: str, source_text: str, around: int = 2, max_chars: int = 1500) -> str:
    """The sentences just before and after the quote in the original text, so pronouns can be resolved.
    The quote may start in one sentence and end in another; the smallest window that holds all of it is used."""
    sents = [s for s in _SENT.split(source_text) if s.strip()]
    norm = [_fold(s) for s in sents]  # keep sentence-final punctuation: a spanning quote contains it
    q = normalise(quote)
    if not q:
        return ""
    for i in range(len(sents)):
        for j in range(i, min(i + 4, len(sents))):  # a quote is one or two sentences; allow a little slack
            if q in " ".join(norm[i : j + 1]):
                return " ".join(sents[max(0, i - around) : j + 1 + around])[:max_chars]
    return ""


def _whole(src: str, i: int, end: int) -> bool:
    """The match must not start or end inside a longer word or number: "$13" is not "$13,000", "6 percent" is
    not "16 percent" or "6.5 percent", "ten" is not "often"."""
    def digit(k):
        return 0 <= k < len(src) and src[k].isdigit()

    if src[i].isalnum() and i > 0:
        if src[i - 1].isalnum() or (src[i].isdigit() and src[i - 1] in ".," and digit(i - 2)):
            return False
    last = src[end - 1]
    if last.isalnum() and end < len(src):
        if src[end].isalnum() or (last.isdigit() and src[end] in ".," and digit(end + 1)):
            return False
    return True


def verify_quote(quote: str, source_text: str) -> bool:
    q, src = normalise(quote), normalise(source_text)
    if len(q.split()) < MIN_WORDS or "..." in q or "…" in q:
        return False
    i = src.find(q)
    while i >= 0:  # every occurrence, in case only a later one stands on word boundaries
        if _whole(src, i, i + len(q)):
            return True
        i = src.find(q, i + 1)
    if q in src:
        return False  # present, but only inside longer words or numbers: do not fall through to fuzzy matching
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
