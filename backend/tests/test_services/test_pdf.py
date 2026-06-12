from pathlib import Path

import pytest

from app.services import _http as _http_mod
from app.services import pdf
from tests.fake_gemini import GeminiTextResponse, RecordingAsyncClient, TransientOnceAsyncClient


def test_chunk_basic():
    content = "# Title\n\nParagraph one.\n\n## Section\n\nParagraph two."
    chunks = pdf.chunk_document(content, chunk_size=50)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)


def test_chunk_respects_size():
    content = "A " * 1000
    chunks = pdf.chunk_document(content, chunk_size=100, overlap=10)
    assert all(len(c) <= 150 for c in chunks)


def test_inject_image_descriptions():
    md = "Some text.\n\n![img-0.jpeg](img-0.jpeg)\n\nMore text."
    descriptions = {"img-0.jpeg": "A flowchart showing the approval process."}
    result = pdf.inject_image_descriptions(md, descriptions)
    assert "flowchart" in result
    assert "![img-0.jpeg]" not in result


def _pdf_markdown_response() -> GeminiTextResponse:
    return GeminiTextResponse('{"markdown": "# Setup Guide\\n\\nUse the API key from settings."}')


class _FakeAsyncClient(RecordingAsyncClient):
    def response_for(self, payload: dict):
        return _pdf_markdown_response()


class _RetryAsyncClient(TransientOnceAsyncClient):
    def success_response_for(self, payload: dict):
        return _pdf_markdown_response()


@pytest.mark.asyncio
async def test_extract_with_ocr_uses_gemini_pdf_input(monkeypatch, tmp_path: Path):
    _FakeAsyncClient.posts = []
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(pdf.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(pdf.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(pdf, "_count_pdf_pages", lambda path: 3)

    markdown, images, page_count = await pdf.extract_with_ocr(pdf_path)

    assert markdown == "# Setup Guide\n\nUse the API key from settings."
    assert images == []
    assert page_count == 3
    post = _FakeAsyncClient.posts[0]
    assert post["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert post["headers"]["x-goog-api-key"] == "gem-key"
    parts = post["json"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "application/pdf"
    assert parts[0]["inline_data"]["data"]
    assert "Transcribe this PDF" in parts[1]["text"]
    assert post["json"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.asyncio
async def test_extract_with_ocr_retries_transient_gemini_errors(monkeypatch, tmp_path: Path):
    _RetryAsyncClient.posts = []
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(pdf.settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(pdf.settings, "gemini_generation_model", "gemini-2.5-flash")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _RetryAsyncClient)
    monkeypatch.setattr(pdf, "_count_pdf_pages", lambda path: 1)

    async def no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(_http_mod.asyncio, "sleep", no_sleep)

    markdown, _, _ = await pdf.extract_with_ocr(pdf_path)

    assert markdown.startswith("# Setup Guide")
    assert len(_RetryAsyncClient.posts) == 2


@pytest.mark.asyncio
async def test_describe_images_is_noop_after_gemini_pdf_extraction():
    assert await pdf.describe_images([{"id": "img-1"}]) == {}
