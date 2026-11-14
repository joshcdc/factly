"""Thin LLM wrapper: prompt in, Pydantic-validated object out (one retry on validation failure)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("LLM_EFFORT", "medium")
FALLBACKS = os.getenv("LLM_FALLBACKS", "default").strip()

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3)


def call_json(system: str, user: str, model_cls: type[T], max_tokens: int = 16000) -> T:
    """Ask the model for JSON matching `model_cls`. Retries once, feeding back the validation error."""
    messages: list[dict] = [{"role": "user", "content": user}]
    extra: dict = {}
    if FALLBACKS:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": FALLBACKS}
    if EFFORT:
        extra["output_config"] = {"effort": EFFORT}

    last_err: Exception | None = None
    for _attempt in range(2):
        raw_text = ""
        try:
            resp = _client().beta.messages.parse(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_format=model_cls,
                **extra,
            )
            if resp.stop_reason == "refusal":
                raise LLMError(f"model refused: {getattr(resp, 'stop_details', None)}")
            raw_text = "".join(b.text for b in resp.content if b.type == "text")
            parsed = resp.parsed_output
            if parsed is None:
                parsed = model_cls.model_validate_json(raw_text)
            return parsed
        except ValidationError as e:
            last_err = e
            messages = messages[:1] + [
                {"role": "assistant", "content": raw_text or "(invalid output)"},
                {
                    "role": "user",
                    "content": f"Your JSON failed validation:\n{e}\nReturn corrected JSON only.",
                },
            ]
    raise LLMError(f"validation failed twice: {last_err}")
