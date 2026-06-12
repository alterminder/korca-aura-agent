import os

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from app.db import connection


class _FakeDriver:
    async def verify_connectivity(self) -> None:
        return None


@pytest.mark.asyncio
async def test_init_driver_uses_only_aura_connection_settings(monkeypatch):
    calls = []

    def fake_driver(uri: str, *, auth: tuple[str, str]):
        calls.append({"uri": uri, "auth": auth})
        return _FakeDriver()

    monkeypatch.setattr(connection.settings, "neo4j_uri_aura", "neo4j+s://aura.example")
    monkeypatch.setattr(connection.settings, "neo4j_user_aura", "aura-user")
    monkeypatch.setattr(connection.settings, "neo4j_pass_aura", "aura-pass")
    monkeypatch.setattr(connection.settings, "neo4j_database_aura", "neo4j")
    monkeypatch.setattr(connection.AsyncGraphDatabase, "driver", fake_driver)

    await connection.init_driver()

    assert calls == [
        {
            "uri": "neo4j+s://aura.example",
            "auth": ("aura-user", "aura-pass"),
        }
    ]


@pytest.mark.asyncio
async def test_init_driver_fails_when_aura_uri_is_missing(monkeypatch):
    def fail_if_called(uri: str, *, auth: tuple[str, str]):
        raise AssertionError("driver should not be created without Aura settings")

    monkeypatch.setattr(connection.settings, "neo4j_uri_aura", "")
    monkeypatch.setattr(connection.settings, "neo4j_user_aura", "aura-user")
    monkeypatch.setattr(connection.settings, "neo4j_pass_aura", "aura-pass")
    monkeypatch.setattr(connection.settings, "neo4j_database_aura", "neo4j")
    monkeypatch.setattr(connection.AsyncGraphDatabase, "driver", fail_if_called)

    with pytest.raises(RuntimeError, match="NEO4J_URI_AURA"):
        await connection.init_driver()
