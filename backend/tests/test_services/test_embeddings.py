import asyncio
import os
from typing import Any

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from app.services import _http as _http_mod
from app.services import embeddings
from tests.fake_gemini import (
    GeminiPayloadResponse,
    RecordingAsyncClient,
    TransientGeminiResponse,
)


class _FakeAsyncClient(RecordingAsyncClient):
    def response_for(self, payload: dict):
        count = len(payload["requests"])
        return GeminiPayloadResponse(
            {
                "embeddings": [
                    {"values": [float(i), float(i + 1), float(i + 2)]} for i in range(count)
                ]
            }
        )


@pytest.mark.asyncio
async def test_generate_embeddings_uses_gemini_batch_endpoint(monkeypatch):
    _FakeAsyncClient.posts = []
    monkeypatch.setattr(embeddings.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(
        embeddings.settings, "gemini_embedding_model", "models/gemini-embedding-001"
    )
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)

    result = await embeddings.generate_embeddings(["first ticket", "second ticket"])

    assert result == [[0.0, 1.0, 2.0], [1.0, 2.0, 3.0]]
    assert _FakeAsyncClient.posts[0]["url"].endswith(
        "/v1beta/models/gemini-embedding-001:batchEmbedContents"
    )
    assert _FakeAsyncClient.posts[0]["headers"]["x-goog-api-key"] == "gem-key"
    assert _FakeAsyncClient.posts[0]["json"] == {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "first ticket"}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            },
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": "second ticket"}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            },
        ]
    }


@pytest.mark.asyncio
async def test_embed_query_uses_retrieval_query_task_type(monkeypatch):
    captured = {}

    async def fake_gemini_embeddings(chunks: list[str], task_type: str, context=None):
        captured["chunks"] = chunks
        captured["task_type"] = task_type
        return [[1.0, 2.0, 3.0]]

    monkeypatch.setattr(embeddings, "_gemini_embeddings", fake_gemini_embeddings)

    result = await embeddings.embed_query("login credentials")

    assert result == [1.0, 2.0, 3.0]
    assert captured == {
        "chunks": ["login credentials"],
        "task_type": "RETRIEVAL_QUERY",
    }


@pytest.mark.asyncio
async def test_generate_embeddings_returns_empty_list_without_api_call(monkeypatch):
    calls = 0

    async def fail_if_called(chunks: list[str], task_type: str, context=None):
        nonlocal calls
        calls += 1
        raise AssertionError("Gemini API should not be called for empty input")

    monkeypatch.setattr(embeddings, "_gemini_embeddings", fail_if_called)

    assert await embeddings.generate_embeddings([]) == []
    assert calls == 0


class _RetryEmbedClient(_FakeAsyncClient):
    async def post(self, url: str, *, headers: dict, json: dict, **kwargs: Any):
        await asyncio.sleep(0)
        self.posts.append({"url": url})
        if len(self.posts) == 1:
            return TransientGeminiResponse()
        count = len(json["requests"])
        return GeminiPayloadResponse({"embeddings": [{"values": [float(i)]} for i in range(count)]})


@pytest.mark.asyncio
async def test_gemini_embeddings_retries_transient_errors(monkeypatch):
    _RetryEmbedClient.posts = []
    monkeypatch.setattr(embeddings.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _RetryEmbedClient)

    original_sleep = _http_mod.asyncio.sleep

    async def no_sleep(delay: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(_http_mod.asyncio, "sleep", no_sleep)

    result = await embeddings.generate_embeddings(["hello"])

    assert result == [[0.0]]
    assert len(_RetryEmbedClient.posts) == 2
