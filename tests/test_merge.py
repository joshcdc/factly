"""Offline tests for entity merging (rules + a stubbed Jev step). Run: python -m tests.test_merge"""
import asyncio

from backend.extraction.merge import resolve


def groups(mentions, ask=None):
    """Merged result as a set of frozensets of names, plus the canon map."""
    canon = asyncio.run(resolve([(n, t, "") for n, t in mentions], ask=ask))
    by_gid = {}
    for (name, _), c in canon.items():
        by_gid.setdefault(c.gid, set()).add(name)
    return {frozenset(g) for g in by_gid.values()}, canon


def merged(a, b, mentions, ask=None):
    gs, _ = groups(mentions, ask)
    return any(a in g and b in g for g in gs)


C, P = "company", "person"

# companies: suffixes, punctuation, case
m = [("Microsoft", C), ("Microsoft Corp.", C), ("microsoft corporation", C), ("OpenAI", C), ("OpenAI, Inc.", C)]
assert merged("Microsoft", "Microsoft Corp.", m) and merged("Microsoft", "microsoft corporation", m)
assert merged("OpenAI", "OpenAI, Inc.", m) and not merged("Microsoft", "OpenAI", m)

# parent / subsidiary / foundation are NOT merged by rules
m = [("OpenAI", C), ("OpenAI Foundation", C), ("OpenAI Group PBC", C), ("Google", C), ("Alphabet", C)]
assert len(groups(m)[0]) == 5

# people: middle initials, honorifics, one typo, surname-only when unique
m = [("Jensen Huang", P), ("Jensen H. Huang", P), ("Dr. Jensen Huang", P), ("Jenson Huang", P), ("Huang", P)]
assert len(groups(m)[0]) == 1
m = [("Jensen Huang", P), ("Lori Huang", P), ("Huang", P)]                  # two Huangs: "Huang" is ambiguous
gs, _ = groups(m)
assert len(gs) == 3, gs
assert not merged("Sam Altman", "Sam Bankman-Fried", [("Sam Altman", P), ("Sam Bankman-Fried", P)])
assert merged("Altman", "Sam Altman", [("Sam Altman", P), ("Altman", P), ("Satya Nadella", P)])

# acronyms, only when exactly one company spells it
m = [("IBM", C), ("International Business Machines Corporation", C)]
assert merged("IBM", "International Business Machines Corporation", m)
m = [("AMD", C), ("Advanced Micro Devices", C), ("Applied Materials Development", C)]
assert len(groups(m)[0]) == 3

# same name, different types: merged (not with people); the most common type wins
gs, canon = groups([("Azure", "concept"), ("Azure", C), ("Azure", C)])
assert len(gs) == 1 and canon[("Azure", "concept")].type == "company"
_, canon = groups([("Jordan", P), ("Jordan", "location")])                      # a person never merges cross-type
assert canon[("Jordan", P)].gid != canon[("Jordan", "location")].gid

# canonical name: most mentioned, then the fullest form; the rest become aliases
_, canon = groups([("Nvidia", C), ("Nvidia", C), ("NVIDIA Corporation", C)])
c = canon[("Nvidia", C)]
assert c.name == "Nvidia" and c.aliases == ["NVIDIA Corporation"], c


# Jev step: asked only about "word subset" pairs, and its answer is applied
asked = []


async def fake_ask(items):
    asked.extend(items)
    return [0 if name == "Meta" else None for name, _, _ in items]   # Meta = Meta Platforms; OpenAI != Foundation

m = [("Meta", C), ("Meta Platforms", C), ("OpenAI", C), ("OpenAI Foundation", C), ("Sam Altman", P)]
assert merged("Meta", "Meta Platforms", m, fake_ask)
assert not merged("OpenAI", "OpenAI Foundation", m, fake_ask)
assert {name for name, _, _ in asked} == {"Meta", "OpenAI"}, asked                # people never go to Jev


async def broken_ask(items):
    raise RuntimeError("Jev down")

assert len(groups(m, broken_ask)[0]) == 5                                          # falls back to rules only
print("merge tests passed")
