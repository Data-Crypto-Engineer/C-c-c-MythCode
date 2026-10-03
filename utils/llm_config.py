"""Gemini settings loader (new in Phase 3).

Reads the key and model from Streamlit secrets (or environment variables).
Accepts BOTH layouts so a misplaced key is still found:

    GEMINI_API_KEY = "..."          # top level (also becomes an env variable)
    GEMINI_MODEL   = "..."

    [llm]                            # or inside a [llm] section
    api_key = "..."
    model   = "..."
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping

from utils.ai_errors import ConfigError, user_message, ErrorKind

_PLACEHOLDER_PREFIXES = ("your_", "your-", "paste", "xxxx", "changeme")


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)
    model: str
    temperature: float = 0.7
    timeout: float = 45.0
    max_retries: int = 2
    max_tokens: int = 1500


def _lookup(mapping: Any, key: str) -> Any:
    """Safe lookup that tolerates st.secrets raising when no secrets file exists."""
    if mapping is None:
        return None
    try:
        return mapping[key]
    except Exception:  # noqa: BLE001 - KeyError, FileNotFoundError, StreamlitSecretNotFoundError...
        return None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip('"').strip("'").strip()
    if not value or value.lower().startswith(_PLACEHOLDER_PREFIXES):
        return None
    return value


def _find(secrets: Any, environ: Mapping[str, str], top_key: str, section_key: str) -> str | None:
    return (
        _clean(_lookup(secrets, top_key))
        or _clean(_lookup(_lookup(secrets, "llm"), section_key))
        or _clean(environ.get(top_key))
    )


def normalize_model(model: str) -> str:
    model = model.strip()
    if model.startswith("models/"):
        model = model[len("models/"):]
    if not model.startswith("gemini/"):
        model = "gemini/" + model
    return model


def load_llm_settings(secrets: Any = None, environ: Mapping[str, str] | None = None) -> LLMSettings:
    """Return validated settings or raise ConfigError (never includes the key)."""
    environ = os.environ if environ is None else environ
    api_key = _find(secrets, environ, "GEMINI_API_KEY", "api_key")
    model = _find(secrets, environ, "GEMINI_MODEL", "model")
    if not api_key:
        raise ConfigError("GEMINI_API_KEY is missing or still a placeholder.")
    if any(ch.isspace() for ch in api_key):
        raise ConfigError("GEMINI_API_KEY contains whitespace; check the secrets file.")
    if not model:
        raise ConfigError("GEMINI_MODEL is missing. Copy a Flash model ID from Google AI Studio.")
    return LLMSettings(api_key=api_key, model=normalize_model(model))


def try_load_settings(secrets: Any = None, environ: Mapping[str, str] | None = None
                      ) -> tuple[LLMSettings | None, str | None]:
    """UI-friendly wrapper: (settings, None) or (None, short non-sensitive message)."""
    try:
        return load_llm_settings(secrets, environ), None
    except ConfigError as exc:
        return None, f"{user_message(ErrorKind.CONFIG)} ({exc})"


def apply_to_environment(settings: LLMSettings, environ: MutableMapping[str, str] | None = None) -> None:
    """CrewAI's Gemini integration reads GEMINI_API_KEY from the environment."""
    target = os.environ if environ is None else environ
    target["GEMINI_API_KEY"] = settings.api_key
