"""LLM provider adapters (Anthropic, OpenAI-compatible)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.errors import ProviderError, ProviderNotConfigured
from app.providers.base import LLMMessage, LLMProvider

log = logging.getLogger(__name__)

TOOL_NAME = "submit_answer"


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text, tolerating code fences and surrounding prose."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError("The model did not return structured JSON.", code="llm_bad_response") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            raise ProviderError("The model returned malformed JSON.", code="llm_bad_response") from None
    if not isinstance(value, dict):
        raise ProviderError("The model returned an unexpected JSON shape.", code="llm_bad_response")
    return value


class AnthropicLLM(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.llm_model or "claude-sonnet-5-5"
        key = settings.anthropic_api_key or settings.llm_api_key
        self._key = key.get_secret_value() if key else ""
        self.timeout = settings.llm_timeout_seconds
        self._client = None

    def check_ready(self) -> None:
        if not self._key:
            raise ProviderNotConfigured(
                "No Anthropic API key is configured. Set ANTHROPIC_API_KEY (or PDFI_LLM_API_KEY) in the "
                "backend environment, or choose another provider with PDFI_LLM_PROVIDER.",
                code="llm_not_configured",
            )

    def _get_client(self):
        self.check_ready()
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._key, timeout=self.timeout, max_retries=1)
        return self._client

    def generate_structured(self, *, system, messages, schema, max_tokens):
        import anthropic

        client = self._get_client()
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                tools=[{"name": TOOL_NAME, "description": "Submit the final answer.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key.", code="llm_auth_failed") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("Anthropic denied access to this model or key.", code="llm_auth_failed") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Model '{self.model}' was not found.", code="llm_model_not_found") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                "Anthropic is rate limiting requests; try again shortly.", code="llm_rate_limited", status_code=503
            ) from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise ProviderError("Could not reach the Anthropic API.", code="llm_unavailable", status_code=503) from exc
        except anthropic.APIError as exc:
            raise ProviderError(f"Anthropic API error ({type(exc).__name__}).", code="llm_failed") from exc
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and isinstance(block.input, dict):
                return block.input
        raise ProviderError("The model did not return a structured answer.", code="llm_bad_response")


class OpenAICompatibleLLM(LLMProvider):
    """Any server exposing ``/chat/completions`` (OpenAI, Ollama, vLLM, LM Studio...)."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model or "gpt-4o-mini"
        self._key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        self.timeout = settings.llm_timeout_seconds
        self._local = self.base_url.startswith(("http://localhost", "http://127.0.0.1"))

    def check_ready(self) -> None:
        if not self._key and not self._local:
            raise ProviderNotConfigured(
                "No LLM API key is configured. Set PDFI_LLM_API_KEY, or point PDFI_LLM_BASE_URL at a local "
                "server such as Ollama (http://localhost:11434/v1).",
                code="llm_not_configured",
            )

    def generate_structured(self, *, system, messages, schema, max_tokens):
        self.check_ready()
        sys_prompt = f"{system}\n\nReply with ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema)}"
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "system", "content": sys_prompt}]
            + [{"role": m.role, "content": m.content} for m in messages],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout)
            if r.status_code == 400:  # some servers reject response_format
                payload.pop("response_format")
                r = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the LLM server.", code="llm_unavailable", status_code=503) from exc
        if r.status_code in (401, 403):
            raise ProviderError("The LLM server rejected the API key.", code="llm_auth_failed")
        if r.status_code == 404:
            raise ProviderError(
                f"Model '{self.model}' or endpoint not found on the LLM server.", code="llm_model_not_found"
            )
        if r.status_code == 429:
            raise ProviderError("The LLM server is rate limiting requests.", code="llm_rate_limited", status_code=503)
        if r.status_code >= 400:
            raise ProviderError(f"The LLM server returned HTTP {r.status_code}.", code="llm_failed")
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError("Unexpected response from the LLM server.", code="llm_bad_response") from exc
        return extract_json_object(content or "")


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAICompatibleLLM(settings)
    return AnthropicLLM(settings)


__all__ = ["AnthropicLLM", "LLMMessage", "OpenAICompatibleLLM", "build_llm_provider", "extract_json_object"]
