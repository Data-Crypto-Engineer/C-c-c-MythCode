"""Builds the single shared CrewAI LLM object (Gemini). CrewAI is imported lazily."""
from __future__ import annotations

from utils.ai_errors import ConfigError
from utils.llm_config import LLMSettings, apply_to_environment


def build_llm(settings: LLMSettings):
    """Return a crewai.LLM for Gemini using the verified 'gemini/<model>' pattern.

    UNVERIFIED in this environment: the optional 'timeout' argument. If the
    installed CrewAI rejects it, we retry without it.
    """
    try:
        from crewai import LLM
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise ConfigError('CrewAI is not installed. Run: pip install "crewai[gemini]"') from exc
    apply_to_environment(settings)
    kwargs = dict(model=settings.model, api_key=settings.api_key,
                  temperature=settings.temperature, max_tokens=settings.max_tokens)
    try:
        return LLM(timeout=settings.timeout, **kwargs)
    except TypeError:  # pragma: no cover
        return LLM(**kwargs)
