from unittest.mock import AsyncMock

import pytest
from neo4j.exceptions import ServiceUnavailable, TransientError

from app.db.connection import get_db
from app.main import app


def _db_raising(exc):
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=exc)

    async def mock_get_db():
        yield mock_session

    return mock_get_db


@pytest.mark.asyncio
async def test_service_unavailable_returns_503(client):
    app.dependency_overrides[get_db] = _db_raising(ServiceUnavailable("Neo4j down"))
    try:
        resp = await client.get("/api/stats")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database temporarily unavailable"


@pytest.mark.asyncio
async def test_transient_error_returns_503(client):
    app.dependency_overrides[get_db] = _db_raising(TransientError("Deadlock"))
    try:
        resp = await client.get("/api/stats")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database temporarily unavailable"
