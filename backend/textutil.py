"""One tokenizer for everything that compares names: entity merging, claim linking and the Jev guard.

It is unicode-aware, folds accents ("José" = "Jose", "Müller" = "Muller") and ignores apostrophes ("O'Brien" =
"OBrien", "Microsoft's" = "Microsoft"), so every module agrees on what a word is.
"""

import re
import unicodedata

_WORD = re.compile(r"[^\W_][\w&'-]*")


def fold(s: str) -> str:
    """Lowercase, accents removed, curly apostrophes straightened."""
    s = unicodedata.normalize("NFKD", s.replace("’", "'").replace("‘", "'"))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(text: str) -> list[str]:
    """Words of `text`, folded, with possessives and apostrophes removed: "Microsoft's O'Brien" -> [microsoft, obrien]."""
    out = []
    for w in _WORD.findall(fold(text)):
        w = w.removesuffix("'s").replace("'", "")
        if w:
            out.append(w)
    return out
