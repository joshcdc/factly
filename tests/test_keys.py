"""API key errors: a missing or rejected key gives a clear message that names the key. Offline.
Run: python -m tests.test_keys"""
import asyncio
import os

from fastapi.testclient import TestClient
from typesafe_sdk import TypeSafeAuthenticationError

import backend.evaluation.jev as jevmod
import backend.intelligence as intel
from backend import keys, pipeline
from backend.api.routes import router  # noqa: F401  (imported so the app below has its routes)
from backend.extraction.schemas import ExtractedEntity, ExtractedExcerpt, SourceExtraction
from backend.main import app
from backend.models.schemas import InvestigationResponse
from backend.models.source import Source

ALL = list(keys.KEYS)
saved = {k: os.environ.get(k) for k in ALL}


def set_keys(**values):
    for k in ALL:
        os.environ.pop(k, None)
    for k, v in values.items():
        os.environ[k] = v


try:
    # --- missing keys are listed by name, and nothing is run
    set_keys()
    assert keys.missing_keys() == ALL
    set_keys(LINKUP_API_KEY="x", ANTHROPIC_API_KEY="  ")   # blank counts as missing
    assert keys.missing_keys() == ["ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"]
    try:
        keys.require_keys()
        raise SystemExit("expected MissingKeysError")
    except keys.MissingKeysError as e:
        msg = str(e)
        assert "ANTHROPIC_API_KEY" in msg and "TYPESAFE_API_KEY" in msg and "LINKUP_API_KEY" not in msg, msg
        assert ".env" in msg and "restart" in msg, msg

    set_keys(LINKUP_API_KEY="x", ANTHROPIC_API_KEY="y", TYPESAFE_API_KEY="z")
    keys.require_keys()                                    # all present: no error

    # --- pipeline: a missing key fails the investigation at once, before any search
    searched = []
    pipeline.retrieval.gather = lambda q: searched.append(q) or []
    set_keys(LINKUP_API_KEY="x", ANTHROPIC_API_KEY="y")    # TYPESAFE_API_KEY missing
    inv = pipeline.run(InvestigationResponse(investigation_id="i1", query="Microsoft controls OpenAI"))
    assert inv.status == "failed" and "TYPESAFE_API_KEY" in inv.error, inv.error
    assert not inv.error.startswith("MissingKeysError"), inv.error     # message only, no class name
    assert searched == [], "a search must not run when a key is missing"

    # --- health endpoint lists missing keys (names only)
    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body == {"ok": True, "missing_keys": ["TYPESAFE_API_KEY"]}, body
    set_keys(LINKUP_API_KEY="secret-a", ANTHROPIC_API_KEY="secret-b", TYPESAFE_API_KEY="secret-c")
    body = client.get("/api/health").json()
    assert body["missing_keys"] == [] and "secret" not in str(body)

    # --- a rejected Anthropic key: every source fails with an auth error
    class AuthenticationError(Exception):                  # the Anthropic SDK's class name is what we match on
        pass

    async def extract_rejected(claim, s):
        raise AuthenticationError("401 invalid x-api-key")

    async def fake_rank(claim, sources):
        intel.rank(sources)

    async def fake_pick(items):
        return [None] * len(items)

    async def fake_summary(claim, name, type_, mentions):
        return None

    intel.rank_async, intel.jev.pick_same, intel.summarise = fake_rank, fake_pick, fake_summary
    SRC = [Source(id=f"source_{i}", url="u", title="t", publisher=f"p{i}.com", source_type="news",
                  content="Microsoft does not control OpenAI's board of directors at all.") for i in (1, 2)]
    intel.extract = extract_rejected
    try:
        intel.analyse("Microsoft controls OpenAI", SRC)
        raise SystemExit("expected AnalysisError")
    except intel.AnalysisError as e:
        assert str(e) == "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.", str(e)

    # --- a rejected TypeSafe key is an error; any other Jev failure still degrades
    async def extract_ok(claim, s):
        return SourceExtraction(
            entities=[ExtractedEntity(name="Microsoft", type="company", description="d"),
                      ExtractedEntity(name="OpenAI", type="company", description="d")], relationships=[],
            excerpts=[ExtractedExcerpt(quote="Microsoft does not control OpenAI's board of directors", reasoning="r")])

    class RejectedKeyClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def system_one(self, **k):
            raise TypeSafeAuthenticationError.__new__(TypeSafeAuthenticationError)

    class FlakyClient(RejectedKeyClient):
        async def system_one(self, **k):
            raise RuntimeError("503 service unavailable")

    intel.extract = extract_ok
    real = jevmod.AsyncTypeSafeClient
    try:
        jevmod.AsyncTypeSafeClient = RejectedKeyClient
        try:
            intel.analyse("Microsoft controls OpenAI", SRC)
            raise SystemExit("expected AnalysisError for a rejected TypeSafe key")
        except intel.AnalysisError as e:
            assert str(e) == "The TypeSafe (Jev) API key was rejected. Check TYPESAFE_API_KEY in .env.", str(e)

        jevmod.AsyncTypeSafeClient = FlakyClient            # an outage degrades: the run completes, evidence unclassified
        r = intel.analyse("Microsoft controls OpenAI", SRC)
        assert r.evidence == [] and "could not be classified" in r.assessments[0].explanation
    finally:
        jevmod.AsyncTypeSafeClient = real
    print("key error tests passed")
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
