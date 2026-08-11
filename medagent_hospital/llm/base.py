"""LLM backend abstraction.

All agent reasoning goes through ``LLMBackend.chat`` so that DeepSeek API,
an OpenAI-compatible vLLM server (HuatuoGPT), and the deterministic rule
fallback are interchangeable.
"""

from __future__ import annotations

import abc
from typing import Any


class LLMBackend(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        """Return the assistant reply for a chat message list."""


class OpenAICompatibleBackend(LLMBackend):
    """OpenAI-compatible chat completions (DeepSeek, vLLM, etc.)."""

    def __init__(self, api_key: str, base_url: str, model: str, name: str = "openai") -> None:
        from openai import OpenAI

        self.name = name
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


class RuleBackend(LLMBackend):
    """Deterministic fallback so the project runs without any API key.

    Keyword-based agent logic will be implemented in the doctor/nurse agents;
    this backend keeps the LLM interface honest in offline mode.
    """

    name = "rule"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        last = messages[-1]["content"] if messages else ""
        return f"[rule-backend] {last}"


def build_llm_backend(settings=None) -> LLMBackend:
    """Build the configured LLM backend; returns RuleBackend when no key exists."""
    from medagent_hospital.config import get_settings

    settings = settings or get_settings()
    if settings.llm_backend in ("deepseek", "openai"):
        if not settings.deepseek_api_key:
            return RuleBackend()
        return OpenAICompatibleBackend(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            name=settings.llm_backend,
        )
    if settings.llm_backend == "huatuo" and settings.huatuo_base_url:
        return OpenAICompatibleBackend(
            api_key="EMPTY",
            base_url=settings.huatuo_base_url,
            model=settings.huatuo_model,
            name="huatuo",
        )
    return RuleBackend()
