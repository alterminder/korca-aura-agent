from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.connection import get_db
from app.limiter import limiter
from app.main import app


async def _fake_db():
    yield object()


@pytest.mark.asyncio
async def test_rate_limiting_on_search(client, monkeypatch):
    # Enable limiter for this specific test
    limiter.enabled = True
    # Reset/clear limiter keys (since slowapi uses standard limits storage, resetting it ensures clean state)
    limiter.reset()

    async def fake_embed_query(query: str):
        return [0.1, 0.2, 0.3]

    async def fake_hybrid_search(*args, **kwargs):
        return []

    monkeypatch.setattr("app.api.routes.search.embed_query", fake_embed_query)
    monkeypatch.setattr("app.api.routes.search.hybrid_search", fake_hybrid_search)
    app.dependency_overrides[get_db] = _fake_db

    try:
        # Make 30 successful requests (Limit is 30/minute)
        for i in range(30):
            resp = await client.post("/api/search", json={"query": f"test-{i}"})
            assert resp.status_code == 200, f"Request {i} failed with status {resp.status_code}"

        # 31st request should be rate-limited (HTTP 429)
        resp = await client.post("/api/search", json={"query": "rate-limited"})
        assert resp.status_code == 429
        body = resp.json()
        assert "Too Many Requests" in body["error"] or "rate limit" in body["error"].lower()

    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.enabled = False


@pytest.mark.asyncio
async def test_rate_limiting_on_upload(client):
    limiter.enabled = True
    limiter.reset()

    fake_pdf = b"%PDF-1.4\n%%EOF"

    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    try:
        with (
            patch(
                "app.services.storage.save_upload_stream",
                new_callable=AsyncMock,
                return_value="hash",
            ),
            patch("app.services.storage.finalize_temp_pdf", return_value="/tmp/fake.pdf"),
            patch("app.worker.process_document") as mock_task,
        ):
            mock_task.delay = MagicMock()

            # 5 successful uploads (limit is 5/minute)
            for i in range(5):
                resp = await client.post(
                    "/api/documents/upload",
                    files={"file": ("test.pdf", fake_pdf, "application/pdf")},
                )
                assert resp.status_code == 202, f"Upload {i} failed with {resp.status_code}"

            # 6th should be rate-limited
            resp = await client.post(
                "/api/documents/upload",
                files={"file": ("test.pdf", fake_pdf, "application/pdf")},
            )
            assert resp.status_code == 429
    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.enabled = False


@pytest.mark.asyncio
async def test_rate_limiting_on_login(client):
    limiter.enabled = True
    limiter.reset()

    try:
        # 5 login attempts (limit is 5/minute) — password doesn't matter, just counting hits
        for i in range(5):
            resp = await client.post("/api/auth/login", json={"password": f"wrong-{i}"})
            assert resp.status_code in (200, 401), (
                f"Attempt {i} unexpected status {resp.status_code}"
            )

        # 6th should be rate-limited regardless of password
        resp = await client.post("/api/auth/login", json={"password": "any"})
        assert resp.status_code == 429
    finally:
        limiter.enabled = False
