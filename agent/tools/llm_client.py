"""Unified LLM client — wraps multiple providers behind a single interface.

Supported providers (set via ``config.yaml`` → ``llm.provider``):
  - ``openai``      : OpenAI API (GPT-4o, GPT-4, etc.)
  - ``anthropic``   : Anthropic Claude API
  - ``deepseek``    : DeepSeek API (OpenAI-compatible endpoint)
  - ``local``       : Any OpenAI-compatible local server (e.g. Ollama, LM Studio)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)

# ── Message type alias ────────────────────────────────────────────────────────
Message = Dict[str, str]   # {"role": "user"|"assistant"|"system", "content": str}


class LLMClient:
    """Provider-agnostic LLM client.

    Parameters
    ----------
    config:
        The ``llm`` section from ``config.yaml``.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._provider = config.get("provider", "openai").lower()
        self._model = config.get("model", "gpt-4o")
        self._temperature = float(config.get("temperature", 0.3))
        self._max_tokens = int(config.get("max_tokens", 8192))
        self._timeout = int(config.get("timeout", 120))
        self._api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"), "")
        self._base_url = config.get("base_url", "") or None
        self._client = self._build_client()

    # ── Public API ─────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Message],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send *messages* to the LLM and return the assistant reply as plain text.

        Parameters
        ----------
        messages:
            Conversation history (list of ``{"role": ..., "content": ...}`` dicts).
        temperature:
            Override the default temperature for this request.
        max_tokens:
            Override the default max_tokens for this request.
        system_prompt:
            Optional system message prepended to *messages*.
        """
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + list(messages)

        t = temperature if temperature is not None else self._temperature
        mt = max_tokens if max_tokens is not None else self._max_tokens

        logger.debug("LLM request | provider=%s model=%s messages=%d", self._provider, self._model, len(messages))

        if self._provider in ("openai", "deepseek", "local"):
            return self._openai_chat(messages, t, mt)
        if self._provider == "anthropic":
            return self._anthropic_chat(messages, t, mt)

        raise ValueError(f"Unsupported LLM provider: {self._provider!r}")

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Convenience wrapper: single-turn completion from a plain string prompt."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    # ── Provider implementations ──────────────────────────────────────────────

    def _build_client(self) -> Any:
        if self._provider in ("openai", "deepseek", "local"):
            try:
                from openai import OpenAI  # type: ignore
            except ImportError as exc:
                raise ImportError("Install 'openai' to use the openai/deepseek/local provider.") from exc
            kwargs: Dict[str, Any] = {"api_key": self._api_key or "sk-placeholder", "timeout": self._timeout}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            return OpenAI(**kwargs)

        if self._provider == "anthropic":
            try:
                import anthropic  # type: ignore
            except ImportError as exc:
                raise ImportError("Install 'anthropic' to use the anthropic provider.") from exc
            return anthropic.Anthropic(api_key=self._api_key or "sk-placeholder")

        raise ValueError(f"Unsupported LLM provider: {self._provider!r}")

    def _openai_chat(self, messages: List[Message], temperature: float, max_tokens: int) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def _anthropic_chat(self, messages: List[Message], temperature: float, max_tokens: int) -> str:
        system = ""
        filtered: List[Message] = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": filtered,
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""
