"""API keys the backend needs. Checked before any work starts so a missing key fails at once with a clear message,
instead of after a search has already run (and cost credits)."""

import os

from dotenv import load_dotenv

load_dotenv()

# environment variable -> what it is used for (shown in the error message)
KEYS = {
    "LINKUP_API_KEY": "Linkup, web search",
    "ANTHROPIC_API_KEY": "Anthropic, Claude reads the sources",
    "TYPESAFE_API_KEY": "TypeSafe, Jev rates the evidence",
}


class MissingKeysError(RuntimeError):
    """One or more API keys are not set. The message is fit to show a user."""


def missing_keys() -> list[str]:
    return [name for name in KEYS if not os.getenv(name, "").strip()]


def require_keys() -> None:
    missing = missing_keys()
    if missing:
        what = "; ".join(f"{name} ({KEYS[name]})" for name in missing)
        raise MissingKeysError(
            f"Missing API key{'s' if len(missing) > 1 else ''}: {what}. Add to the .env file in the repo root "
            "(see .env.example) and restart the backend.")
