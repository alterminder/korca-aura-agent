import pytest

from app.db.connection import get_db
from app.main import app


async def _fake_db():
    yield object()


@pytest.mark.asyncio
async def test_ask_returns_sources_when_answer_generation_fails(client, monkeypatch):
    async def fake_embed_query(question: str):
        return [0.1, 0.2, 0.3]

    async def fake_hybrid_search(*args, **kwargs):
        return [
            {
                "id": "chunk-1",
                "document_id": "doc-1",
                "content": "Credential reset instructions.",
                "score": 0.91,
            }
        ]

    async def fake_answer_question(question: str, chunks: list[dict]):
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr("app.api.routes.search.embed_query", fake_embed_query)
    monkeypatch.setattr("app.api.routes.search.hybrid_search", fake_hybrid_search)
    monkeypatch.setattr("app.api.routes.search.answer_question", fake_answer_question)
    app.dependency_overrides[get_db] = _fake_db

    try:
        resp = await client.post("/api/search/ask", json={"question": "credentials"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert "temporarily unavailable" in body["answer"]
    assert body["sources"][0]["content"] == "Credential reset instructions."
