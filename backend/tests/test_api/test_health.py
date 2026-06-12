import pytest

from app.api.routes import health
from app.api.routes.health import ClientLoadItem, NeedsReviewResponse


class _FakeResult:
    def __init__(self, record=None, rows=None):
        self._record = record
        self._rows = rows or []

    async def single(self):
        return self._record

    async def data(self):
        return self._rows


class _FakeDb:
    def __init__(self, results=None):
        self.queries = []
        self._results = list(results or [])

    async def run(self, query, **params):
        self.queries.append((query, params))
        if self._results:
            return self._results.pop(0)
        return _FakeResult({"n": 7})


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_needs_review_counts_only_staged_tickets():
    db = _FakeDb()

    result = await health.needs_review(db)

    assert result == NeedsReviewResponse(staged=7)
    assert len(db.queries) == 1
    assert "ingest_status = 'staged'" in db.queries[0][0]
    assert "ROUTED_TO" not in db.queries[0][0]


@pytest.mark.asyncio
async def test_recent_activity_uses_routing_events():
    db = _FakeDb([_FakeResult(rows=[])])

    result = await health.recent_activity(db)

    assert result == []
    query = db.queries[0][0]
    assert "HAS_ROUTING_EVENT" in query
    assert "RoutingEvent" in query
    assert "ROUTED_TO" not in query


@pytest.mark.asyncio
async def test_recent_activity_returns_latest_event_per_ticket():
    db = _FakeDb([_FakeResult(rows=[])])

    await health.recent_activity(db)

    query = db.queries[0][0]
    assert "collect(e)[0] AS latest_event" in query
    assert "latest_event.created_at DESC" in query
    assert "LIMIT 15" in query


@pytest.mark.asyncio
async def test_client_load_counts_assigned_tickets_by_client():
    db = _FakeDb(
        [
            _FakeResult(
                rows=[
                    {"name": "Acme", "domain": "acme.test", "ticket_count": 5},
                ]
            )
        ]
    )

    result = await health.client_load(db)

    assert result == [ClientLoadItem(name="Acme", domain="acme.test", ticket_count=5)]
    query = db.queries[0][0]
    assert "ASSIGNED_TO" in query
    assert "FROM" in query
    assert "ROUTED_TO" not in query
