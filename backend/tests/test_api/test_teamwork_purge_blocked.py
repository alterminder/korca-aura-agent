import asyncio

import pytest

from app.config import settings as _settings
from app.services.teamwork_sync import _subject_blocklist_prefixes

TEAMWORK_IMPORT_ROUTE = "app.api.routes.teamwork_import"


async def _async_value(value):
    await asyncio.sleep(0)
    return value


@pytest.fixture(autouse=True)
def _default_no_full_import_running(monkeypatch):
    async def fake_running():
        return await _async_value(False)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.is_full_import_running", fake_running)


class _FakeResult:
    def __init__(self, rows=None, single_record=None):
        self._rows = rows or []
        self._single_record = single_record

    async def data(self):
        return await _async_value(self._rows)

    async def single(self):
        return await _async_value(self._single_record)


class _FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, query, **params):
        await _async_value(None)
        self.calls.append((query, params))
        return self.result


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return await _async_value(self._session)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


@pytest.mark.asyncio
async def test_purge_blocked_preview_filters_default_blocklist_in_cypher(client, monkeypatch):
    result = _FakeResult(
        rows=[
            {"id": "1", "subject": "Out of Office: Back tomorrow"},
            {"id": "2", "subject": "Automatic reply: PTO"},
        ]
    )
    session = _FakeSession(result)
    monkeypatch.setattr(
        _settings, "teamwork_subject_blocklist", ["out of office:", "automatic reply:"]
    )
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))

    resp = await client.get("/api/import/teamwork/purge-blocked/preview")

    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    query, params = session.calls[0]
    assert "ANY(pref IN $prefixes" in query
    assert "STARTS WITH toLower(pref)" in query
    assert params == {"prefixes": list(_subject_blocklist_prefixes())}


@pytest.mark.asyncio
async def test_purge_blocked_preview_filters_custom_prefix_in_cypher(client, monkeypatch):
    result = _FakeResult(rows=[{"id": "1", "subject": "Job: Personal trainer"}])
    session = _FakeSession(result)
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))

    resp = await client.get(
        "/api/import/teamwork/purge-blocked/preview",
        params={"prefix": "Job: "},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "count": 1,
        "samples": ["Job: Personal trainer"],
        "filter": 'subject starts with "Job: "',
    }
    query, params = session.calls[0]
    assert "toLower(t.subject) STARTS WITH toLower($prefix)" in query
    assert params == {"prefix": "Job: "}


@pytest.mark.asyncio
async def test_purge_blocked_tickets_deletes_matches_and_routing_events_in_cypher(
    client, monkeypatch
):
    result = _FakeResult(single_record={"deleted": 3})
    session = _FakeSession(result)
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))

    resp = await client.post("/api/import/teamwork/purge-blocked", params={"prefix": "Job: "})

    assert resp.status_code == 200
    assert resp.json() == {"deleted": 3}
    query, params = session.calls[0]
    assert "OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)" in query
    assert "DETACH DELETE t, e" in query
    assert "RETURN count(DISTINCT t) AS deleted" in query
    assert params == {"prefix": "Job: "}
