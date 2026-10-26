"""Provider adapters, exercised against in-process fake HTTP transports (no network)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import anthropic
import httpx
import httpx2
import pytest

from app.config import Settings
from app.errors import ProviderError, ProviderNotConfigured
from app.providers.base import LLMMessage
from app.providers.embeddings import OpenAIEmbedding, build_embedding_provider
from app.providers.llm import AnthropicLLM, OpenAICompatibleLLM, build_llm_provider, extract_json_object

SECRET = "sk-test-SECRET-123"
SCHEMA = {"type": "object"}
MSGS = [LLMMessage("user", "hi")]


def settings(tmp_path: Path, **kw) -> Settings:
    return Settings(data_dir=tmp_path, **kw)


# ---- JSON extraction -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here you go: {"a": 1} hope that helps'],
)
def test_extract_json_object_tolerates_fences_and_prose(text: str) -> None:
    assert extract_json_object(text) == {"a": 1}


@pytest.mark.parametrize("text", ["no json here", "{broken", "[1, 2]"])
def test_extract_json_object_rejects_garbage(text: str) -> None:
    with pytest.raises(ProviderError) as e:
        extract_json_object(text)
    assert e.value.code == "llm_bad_response"


# ---- Anthropic ---------------------------------------------------------------------------------------
def anthropic_llm(tmp_path: Path, handler, key: str | None = SECRET) -> AnthropicLLM:
    llm = AnthropicLLM(settings(tmp_path, anthropic_api_key=key))
    if key:
        llm._client = anthropic.Anthropic(
            api_key=key,
            base_url="http://anthropic.test",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        )
    return llm


def test_anthropic_requires_a_key_and_says_how_to_set_it(tmp_path: Path) -> None:
    llm = AnthropicLLM(settings(tmp_path))
    with pytest.raises(ProviderNotConfigured) as e:
        llm.check_ready()
    assert "ANTHROPIC_API_KEY" in e.value.message and e.value.code == "llm_not_configured"


def test_anthropic_forces_the_answer_tool_and_returns_its_input(tmp_path: Path) -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("x-api-key")
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "m",
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [{"type": "tool_use", "id": "tu_1", "name": "submit_answer", "input": {"answer": "ok"}}],
            },
        )

    out = anthropic_llm(tmp_path, handler).generate_structured(
        system="sys", messages=MSGS, schema=SCHEMA, max_tokens=50
    )
    assert out == {"answer": "ok"}
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "submit_answer"}
    assert seen["body"]["system"] == "sys" and seen["key"] == SECRET


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "llm_auth_failed"),
        (403, "llm_auth_failed"),
        (404, "llm_model_not_found"),
        (429, "llm_rate_limited"),
        (500, "llm_failed"),
    ],
)
def test_anthropic_errors_are_mapped_and_never_leak_the_key(tmp_path: Path, status: int, code: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": f"bad key {SECRET}"}})

    with pytest.raises(ProviderError) as e:
        anthropic_llm(tmp_path, handler).generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e.value.code == code and SECRET not in e.value.message


def test_anthropic_connection_failure_and_missing_tool_output(tmp_path: Path) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    with pytest.raises(ProviderError) as e:
        anthropic_llm(tmp_path, down).generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e.value.code == "llm_unavailable" and e.value.status_code == 503

    def text_only(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "m",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [{"type": "text", "text": "hi"}],
            },
        )

    with pytest.raises(ProviderError) as e2:
        anthropic_llm(tmp_path, text_only).generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e2.value.code == "llm_bad_response"


# ---- OpenAI-compatible LLM -------------------------------------------------------------------------------
def patch_post(monkeypatch: pytest.MonkeyPatch, handler) -> list[dict]:
    calls: list[dict] = []

    def fake_post(url: str, **kw) -> httpx.Response:
        calls.append(copy.deepcopy({"url": url, **kw}))
        return handler(len(calls), kw)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def chat(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}, request=httpx.Request("POST", "http://x")
    )


def test_openai_compatible_parses_json_and_sends_bearer_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_post(monkeypatch, lambda n, kw: chat('```json\n{"answer": "x"}\n```'))
    llm = OpenAICompatibleLLM(settings(tmp_path, llm_provider="openai", llm_api_key=SECRET))
    assert llm.generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5) == {"answer": "x"}
    assert calls[0]["headers"] == {"Authorization": f"Bearer {SECRET}"}
    assert calls[0]["json"]["messages"][0]["role"] == "system"


def test_openai_compatible_retries_without_response_format_when_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = patch_post(monkeypatch, lambda n, kw: httpx.Response(400) if n == 1 else chat('{"answer": "y"}'))
    llm = OpenAICompatibleLLM(settings(tmp_path, llm_provider="openai", llm_base_url="http://localhost:11434/v1"))
    assert llm.generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5) == {"answer": "y"}
    assert "response_format" in calls[0]["json"] and "response_format" not in calls[1]["json"]


def test_openai_compatible_requires_key_unless_local(tmp_path: Path) -> None:
    with pytest.raises(ProviderNotConfigured) as e:
        OpenAICompatibleLLM(settings(tmp_path, llm_provider="openai")).check_ready()
    assert "PDFI_LLM_API_KEY" in e.value.message
    OpenAICompatibleLLM(
        settings(tmp_path, llm_provider="openai", llm_base_url="http://localhost:11434/v1")
    ).check_ready()


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "llm_auth_failed"), (404, "llm_model_not_found"), (429, "llm_rate_limited"), (503, "llm_failed")],
)
def test_openai_compatible_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    patch_post(monkeypatch, lambda n, kw: httpx.Response(status, text=f"leaked {SECRET}"))
    llm = OpenAICompatibleLLM(settings(tmp_path, llm_provider="openai", llm_api_key=SECRET))
    with pytest.raises(ProviderError) as e:
        llm.generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e.value.code == code and SECRET not in e.value.message


def test_openai_compatible_network_error_and_bad_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = OpenAICompatibleLLM(settings(tmp_path, llm_provider="openai", llm_api_key=SECRET))

    def boom(n: int, kw: dict) -> httpx.Response:
        raise httpx.ConnectError("refused")

    patch_post(monkeypatch, boom)
    with pytest.raises(ProviderError) as e:
        llm.generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e.value.code == "llm_unavailable"
    patch_post(monkeypatch, lambda n, kw: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(ProviderError) as e2:
        llm.generate_structured(system="s", messages=MSGS, schema=SCHEMA, max_tokens=5)
    assert e2.value.code == "llm_bad_response"


# ---- OpenAI embeddings ------------------------------------------------------------------------------------
def test_openai_embeddings_batch_normalise_and_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(n: int, kw: dict) -> httpx.Response:
        inputs = kw["json"]["input"]
        data = [{"index": i, "embedding": [3.0, 4.0]} for i in reversed(range(len(inputs)))]
        return httpx.Response(200, json={"data": data})

    calls = patch_post(monkeypatch, handler)
    emb = OpenAIEmbedding(
        settings(tmp_path, embedding_provider="openai", embedding_api_key=SECRET, embedding_batch_size=2)
    )
    vecs = emb.embed_documents(["a", "b", "c"])
    assert vecs.shape == (3, 2) and len(calls) == 2
    assert vecs[0].tolist() == pytest.approx([0.6, 0.8])


def test_openai_embeddings_not_configured_and_auth_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderNotConfigured):
        OpenAIEmbedding(settings(tmp_path, embedding_provider="openai")).embed_query("x")
    patch_post(monkeypatch, lambda n, kw: httpx.Response(401))
    emb = OpenAIEmbedding(settings(tmp_path, embedding_provider="openai", embedding_api_key=SECRET))
    with pytest.raises(ProviderError) as e:
        emb.embed_query("x")
    assert e.value.code == "embedding_auth_failed"


def test_factories_pick_the_configured_provider(tmp_path: Path) -> None:
    assert build_embedding_provider(settings(tmp_path, embedding_provider="hash")).model_id == "hash-512"
    assert build_llm_provider(settings(tmp_path, llm_provider="openai")).name == "openai"
    assert build_llm_provider(settings(tmp_path)).name == "anthropic"
