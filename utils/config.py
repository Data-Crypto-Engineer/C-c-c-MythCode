"""Reads LLM settings from Streamlit Secrets (or environment variables for local tests).

Phase 1 only reports whether AI is configured; nothing here calls a model.
"""
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from utils.error_handler import ConfigError

SUPPORTED_PROVIDERS = ("gemini",)


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str = ""

    def __repr__(self) -> str:  # never print the key
        return f"LLMSettings(provider={self.provider!r}, model={self.model!r}, api_key=<hidden>)"


def _read_raw() -> dict:
    """Return the [llm] table from st.secrets, falling back to env vars."""
    try:
        import streamlit as st

        section = st.secrets.get("llm", None)
        if section is not None:
            return dict(section)
    except Exception:  # no secrets file, malformed TOML, or not running in Streamlit
        pass
    return {
        "provider": os.getenv("MYTHCODE_LLM_PROVIDER", ""),
        "model": os.getenv("MYTHCODE_LLM_MODEL", ""),
        "api_key": os.getenv("MYTHCODE_LLM_API_KEY", ""),
    }


def parse_settings(raw: dict) -> LLMSettings:
    provider = str(raw.get("provider", "")).strip().lower()
    model = str(raw.get("model", "")).strip()
    api_key = str(raw.get("api_key", "")).strip()
    if not provider and not model and not api_key:
        raise ConfigError("No [llm] settings found. Copy .streamlit/secrets.toml.example to .streamlit/secrets.toml.")
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"Unsupported provider. Supported: {', '.join(SUPPORTED_PROVIDERS)}.")
    if not model:
        raise ConfigError("Missing 'model' in [llm] secrets.")
    if not api_key or api_key.startswith("YOUR_"):
        raise ConfigError("Missing 'api_key' in [llm] secrets (still a placeholder?).")
    return LLMSettings(provider=provider, model=model, api_key=api_key)


def load_llm_settings() -> LLMSettings:
    return parse_settings(_read_raw())


def llm_status() -> Tuple[bool, Optional[str]]:
    """(configured, message) for display; never raises."""
    try:
        load_llm_settings()
        return True, None
    except ConfigError as exc:
        return False, str(exc)
