import sys
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from app.services import _http as _http_mod
from app.services import llm
from tests.fake_gemini import (
    GeminiTextResponse,
    RecordingAsyncClient,
    TransientGeminiResponse,
    TransientOnceAsyncClient,
)


class _FakeAsyncClient(RecordingAsyncClient):
    def response_for(self, payload: dict):
        prompt = payload["contents"][0]["parts"][0]["text"]
        if "Extract the following" in prompt:
            return GeminiTextResponse(
                '{"title":"Setup Guide","author":"Internal Docs","summary":"A setup guide.",'
                '"topics":["google indexing api","wordpress"],"document_type":"guide"}'
            )
        if "Return a clean plain-text request summary" in prompt:
            return GeminiTextResponse(
                "Customer reports that the website font looks incorrect after a WordPress update."
            )
        if "return a JSON array" in prompt:
            return GeminiTextResponse('["wordpress", "css", "teamwork desk"]')
        return GeminiTextResponse("Use the reset credentials procedure from the source document.")


class _RetryAsyncClient(TransientOnceAsyncClient):
    def success_response_for(self, payload: dict):
        return GeminiTextResponse(
            '{"title":"Setup Guide","author":null,"summary":"A setup guide.",'
            '"topics":["google indexing api"],"document_type":"guide"}'
        )


@pytest.mark.asyncio
async def test_extract_metadata_uses_gemini_structured_output(monkeypatch):
    _FakeAsyncClient.posts = []
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)

    metadata = await llm.extract_metadata("# Setup Guide\n\nConfigure the plugin.")

    assert metadata == {
        "title": "Setup Guide",
        "author": "Internal Docs",
        "summary": "A setup guide.",
        "topics": ["google indexing api", "wordpress"],
        "document_type": "guide",
    }
    post = _FakeAsyncClient.posts[0]
    assert post["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert post["headers"]["x-goog-api-key"] == "gem-key"
    assert post["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in post["json"]["generationConfig"]


@pytest.mark.asyncio
async def test_extract_metadata_retries_transient_gemini_errors(monkeypatch):
    _RetryAsyncClient.posts = []
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _RetryAsyncClient)

    original_sleep = _http_mod.asyncio.sleep

    async def no_sleep(delay: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(_http_mod.asyncio, "sleep", no_sleep)

    metadata = await llm.extract_metadata("# Setup Guide")

    assert metadata["title"] == "Setup Guide"
    assert len(_RetryAsyncClient.posts) == 2


@pytest.mark.asyncio
async def test_generation_failure_logs_error_spend(monkeypatch):
    class _AlwaysFailAsyncClient(_FakeAsyncClient):
        async def post(self, url: str, *, headers: dict, json: dict, **kwargs: Any):
            await _http_mod.asyncio.sleep(0)
            self.posts.append({"url": url})
            return TransientGeminiResponse()

    _AlwaysFailAsyncClient.posts = []
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _AlwaysFailAsyncClient)

    original_sleep = _http_mod.asyncio.sleep

    async def no_sleep(delay: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(_http_mod.asyncio, "sleep", no_sleep)

    with capture_logs() as logs:
        with pytest.raises(httpx.HTTPStatusError):
            await llm.answer_question(
                "How do I reset credentials?",
                [{"document_id": "doc-1", "score": 0.9, "content": "reset steps"}],
            )

    spend = [e for e in logs if e["event"] == "gemini_spend"]
    assert spend, "expected a gemini_spend event for the failed generation"
    assert spend[-1]["result"] == "error"
    assert spend[-1]["kind"] == "generate"
    assert spend[-1]["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_answer_question_uses_gemini_generation(monkeypatch):
    _FakeAsyncClient.posts = []
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)

    answer = await llm.answer_question(
        "How do I reset credentials?",
        [
            {
                "document_id": "doc-1",
                "score": 0.91,
                "content": "Reset credentials from the Teamwork account settings page.",
            }
        ],
    )

    assert answer == "Use the reset credentials procedure from the source document."
    post = _FakeAsyncClient.posts[0]
    assert post["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert post["headers"]["x-goog-api-key"] == "gem-key"
    prompt = post["json"]["contents"][0]["parts"][0]["text"]
    assert "How do I reset credentials?" in prompt
    assert "Reset credentials from the Teamwork account settings page." in prompt


@pytest.mark.asyncio
async def test_summarize_ticket_uses_gemini_without_importing_mistral(monkeypatch):
    class _BlockedMistral:
        def __getattr__(self, name: str):
            raise AssertionError("summarize_ticket should not import or call Mistral")

    _FakeAsyncClient.posts = []
    monkeypatch.setitem(sys.modules, "mistralai", _BlockedMistral())
    monkeypatch.setitem(sys.modules, "mistralai.client", _BlockedMistral())
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)

    summary = await llm.summarize_ticket(
        "Website font",
        "The website font is wrong. We updated CSS and confirmed.",
        "Closed",
    )

    assert (
        summary
        == "Customer reports that the website font looks incorrect after a WordPress update."
    )
    post = _FakeAsyncClient.posts[0]
    assert post["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert post["headers"]["x-goog-api-key"] == "gem-key"
    prompt = post["json"]["contents"][0]["parts"][0]["text"]
    assert "Website font" in prompt
    assert "The website font is wrong" in prompt
    assert "PROBLEM:" not in prompt
    assert "RESOLUTION:" not in prompt
    assert "resolution" not in prompt.lower()


@pytest.mark.asyncio
async def test_generate_expert_skills_uses_gemini_without_importing_mistral(monkeypatch):
    class _BlockedMistral:
        def __getattr__(self, name: str):
            raise AssertionError("generate_expert_skills should not import or call Mistral")

    _FakeAsyncClient.posts = []
    monkeypatch.setitem(sys.modules, "mistralai", _BlockedMistral())
    monkeypatch.setitem(sys.modules, "mistralai.client", _BlockedMistral())
    monkeypatch.setattr(llm.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(llm.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)

    skills = await llm.generate_expert_skills(
        "Alex",
        ["PROBLEM: WordPress CSS issue.\nRESOLUTION: Updated theme CSS."],
    )

    assert skills == ["wordpress", "css", "teamwork desk"]
    post = _FakeAsyncClient.posts[0]
    assert post["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert post["headers"]["x-goog-api-key"] == "gem-key"
