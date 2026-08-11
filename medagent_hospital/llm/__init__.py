"""LLM backend layer: OpenAI-compatible clients and deterministic fallback."""

from medagent_hospital.llm.base import (
    LLMBackend,
    OpenAICompatibleBackend,
    RuleBackend,
    build_llm_backend,
)

__all__ = [
    "LLMBackend",
    "OpenAICompatibleBackend",
    "RuleBackend",
    "build_llm_backend",
]
