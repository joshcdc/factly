"""Entity merging: precise rules first, then Jev for the remaining ambiguous pairs.

A wrong merge (a parent with its subsidiary, two people who share a surname) is worse than a leftover duplicate,
so every rule needs an unambiguous match and the Jev step needs high confidence.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from backend.textutil import tokens

MAX_JEV_ASKS = 20  # bound the extra Jev calls per investigation

_STOP = {"the", "a", "an", "of", "and", "for", "in", "on", "at", "to"}
_HONORIFIC = {"dr", "mr", "mrs", "ms", "prof", "professor", "sir", "dame"}
_SUFFIX = {"inc", "incorporated", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "company", "group",
           "gmbh", "ag", "sa"}
_SPECIFIC = ["person", "company", "location", "event", "concept"]  # tie-break when mentions disagree on type


def words(name: str, drop_suffix: bool = False) -> list[str]:
    ws = [w for w in tokens(name) if w not in _STOP and w not in _HONORIFIC]
    if drop_suffix:
        ws = [w for w in ws if w not in _SUFFIX] or ws
    return ws


def same_word(a: str, b: str) -> bool:
    """Equal, or one typo apart in words of 5+ letters ('jenson' ~ 'jensen')."""
    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.8)


@dataclass
class Canon:
    gid: int
    name: str
    type: str
    description: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class _Variant:
    name: str
    type: str
    description: str
    count: int = 0


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def _apply_rules(vs: list[_Variant], uf: _UnionFind) -> None:
    # 1. Same name after normalising case, punctuation and company suffixes ("Microsoft Corp." = "Microsoft").
    #    Different types merge only here, and never with a person ("Azure" concept = "Azure" company).
    by_key: dict[str, int] = {}
    for i, v in enumerate(vs):
        k = "".join(words(v.name, drop_suffix=v.type in ("company", "concept")))
        if not k:
            continue
        j = by_key.setdefault(k, i)
        if j != i and (vs[j].type == v.type or "person" not in (vs[j].type, v.type)):
            uf.union(i, j)

    # 2. People: same first and last word, ignoring middle names, initials and one typo
    #    ("Jensen H. Huang" = "Jensen Huang" = "Jenson Huang"; "Lori Huang" stays separate).
    people = [i for i, v in enumerate(vs) if v.type == "person"]
    full = [i for i in people if len(words(vs[i].name)) >= 2]
    for x, i in enumerate(full):
        wi = words(vs[i].name)
        for j in full[x + 1:]:
            wj = words(vs[j].name)
            if same_word(wi[0], wj[0]) and same_word(wi[-1], wj[-1]):
                uf.union(i, j)

    # 3. A one-word person ("Huang") joins the only person group with that first or last name.
    for i in people:
        w = words(vs[i].name)
        if len(w) != 1:
            continue
        groups = {uf.find(j) for j in full
                  if same_word(w[0], words(vs[j].name)[0]) or same_word(w[0], words(vs[j].name)[-1])}
        if len(groups) == 1:
            uf.union(i, groups.pop())

    # 4. Company acronyms: "IBM" joins the only company whose initials spell it.
    companies = [i for i, v in enumerate(vs) if v.type == "company"]
    for i in companies:
        w = words(vs[i].name, drop_suffix=True)
        if len(w) != 1 or not 2 <= len(w[0]) <= 6 or not w[0].isalpha():
            continue
        groups = {uf.find(j) for j in companies
                  if len(wj := words(vs[j].name, drop_suffix=True)) >= 2 and "".join(x[0] for x in wj) == w[0]}
        if len(groups) == 1:
            uf.union(i, groups.pop())


def _jev_questions(vs: list[_Variant], uf: _UnionFind) -> list[tuple[int, list[int]]]:
    """Pairs the rules can't settle: a non-person name whose words all appear in a longer name of the same type
    ("Meta" / "Meta Platforms", but also "OpenAI" / "OpenAI Foundation", which Jev must reject)."""
    reps: dict[int, int] = {}
    for i in range(len(vs)):
        r = uf.find(i)
        if r not in reps or vs[i].count > vs[reps[r]].count:
            reps[r] = i
    groups = list(reps.values())
    asks = []
    for i in groups:
        if vs[i].type == "person":
            continue
        wi = set(words(vs[i].name, drop_suffix=True))
        cands = [j for j in groups if j != i and vs[j].type == vs[i].type
                 and wi < set(words(vs[j].name, drop_suffix=True))]
        if wi and cands:
            asks.append((i, cands[:5]))
    return asks[:MAX_JEV_ASKS]


async def resolve(mentions: list[tuple[str, str, str]], ask=None) -> dict[tuple[str, str], Canon]:
    """mentions: (name, type, description), one per entity per source.
    Returns {(name, type): Canon}, the merged entity each mention belongs to.
    `ask` is the Jev step, async [(name, desc, [(cand_name, cand_desc)])] -> [index | None]; None skips it."""
    variants: dict[tuple[str, str], _Variant] = {}
    for name, type_, desc in mentions:
        v = variants.setdefault((name, type_), _Variant(name, type_, desc))
        v.count += 1
    vs = list(variants.values())
    uf = _UnionFind(len(vs))
    _apply_rules(vs, uf)

    if ask is not None:
        questions = _jev_questions(vs, uf)
        if questions:
            try:
                answers = await ask([(vs[i].name, vs[i].description,
                                      [(vs[j].name, vs[j].description) for j in cands]) for i, cands in questions])
            except Exception:  # Jev down: keep the rule-based result
                answers = [None] * len(questions)
            for (i, cands), a in zip(questions, answers):
                if a is not None and 0 <= a < len(cands):
                    uf.union(i, cands[a])

    members: dict[int, list[int]] = {}
    for i in range(len(vs)):
        members.setdefault(uf.find(i), []).append(i)
    out: dict[tuple[str, str], Canon] = {}
    for gid, idx in enumerate(members.values()):  # members keeps first-seen order
        names = Counter()
        types = Counter()
        for i in idx:
            names[vs[i].name] += vs[i].count
            types[vs[i].type] += vs[i].count
        # most mentioned; then the most words ("Jensen Huang" over "Huang"); then the shortest spelling, which drops
        # legal suffixes ("Microsoft" over "Microsoft Corp.")
        name = max(names, key=lambda n: (names[n], len(words(n, drop_suffix=True)), -len(n)))
        type_ = max(types, key=lambda t: (types[t], -_SPECIFIC.index(t)))
        desc = next(vs[i].description for i in idx if vs[i].name == name)
        canon = Canon(gid, name, type_, desc, sorted({vs[i].name for i in idx} - {name}))
        for i in idx:
            out[(vs[i].name, vs[i].type)] = canon
    return out
