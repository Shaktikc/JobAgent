"""Task 3/10 model overrides, sharing the general LLM connection settings.

Only an explicit, nonblank override replaces the general model. Resolving one
purpose never mutates Settings or reads another purpose's model override.
"""

from __future__ import annotations

from src.configuration import LLMSettings, Settings, clean_model_id


def resume_llm_settings(settings: Settings) -> LLMSettings:
    """Task 3 descriptions and matching, including Task 15's shared describer."""
    return settings.llm.model_copy(
        update={"model": clean_model_id(settings.llm.resume_model) or settings.llm.model}
    )


def answer_llm_settings(settings: Settings) -> LLMSettings:
    """Task 10 store-backed answers, including the select-only answer chooser."""
    return settings.llm.model_copy(
        update={"model": clean_model_id(settings.llm.answers_model) or settings.llm.model}
    )
