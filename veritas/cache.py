"""JSON file cache of full reports, keyed on a hash of the input, for offline demo replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import Report

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "reports"


def key(text: str, pub_date: str | None) -> str:
    raw = json.dumps({"text": " ".join(text.split()), "pub_date": pub_date or ""}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get(text: str, pub_date: str | None) -> Report | None:
    p = CACHE_DIR / f"{key(text, pub_date)}.json"
    if not p.exists():
        return None
    return Report.model_validate_json(p.read_text())


def put(report: Report) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{key(report.input_text, report.pub_date)}.json"
    p.write_text(report.model_dump_json(indent=2))
    return p


def list_cached() -> list[Report]:
    if not CACHE_DIR.exists():
        return []
    files = sorted(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [Report.model_validate_json(f.read_text()) for f in files]
