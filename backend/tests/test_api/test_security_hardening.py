import pytest

from app.config import Settings


def test_cors_origins_parsing_comma_separated(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://a.com,http://b.com, http://c.com ")
    s = Settings()
    assert s.cors_allowed_origins == ["http://a.com", "http://b.com", "http://c.com"]


def test_cors_origins_parsing_json_list(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://a.com", "http://b.com"]')
    s = Settings()
    assert s.cors_allowed_origins == ["http://a.com", "http://b.com"]


@pytest.mark.asyncio
async def test_clients_query_param_bounds(client):
    # Test invalid limit > 500
    res_large = await client.get("/api/clients?limit=501")
    assert res_large.status_code == 422

    # Test invalid limit < 1
    res_small = await client.get("/api/clients?limit=0")
    assert res_small.status_code == 422

    # Test invalid offset < 0
    res_neg = await client.get("/api/clients?offset=-5")
    assert res_neg.status_code == 422


