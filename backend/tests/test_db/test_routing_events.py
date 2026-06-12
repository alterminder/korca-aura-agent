import pytest

from app.db import queries


class _FakeResult:
    def __init__(self, record=None):
        self._record = record or {}

    async def single(self):
        return self._record

    async def data(self):
        return self._record.get("rows", [])


class _FakeSession:
    def __init__(self, records=None):
        self.calls = []
        self._records = list(records or [])

    async def run(self, query, **params):
        self.calls.append((query, params))
        record = self._records.pop(0) if self._records else {}
        return _FakeResult(record)


@pytest.mark.asyncio
async def test_record_aura_routing_event_creates_event_and_recommended_expert_edge():
    session = _FakeSession([{"event": {"id": "event-1", "outcome": "wrong"}}])

    event = await queries.record_aura_routing_event(
        session,
        ticket_id="9846499",
        expert_email="expert@example.com",
        expert_name="Example Expert",
        confidence="aura",
        mode="manual",
        action="stored",
        trace_id="trace-1",
    )

    query, params = session.calls[0]
    assert "RoutingEvent" in query
    assert "HAS_ROUTING_EVENT" in query
    assert "RECOMMENDED_EXPERT" in query
    assert "ASSIGNED_TO" in query
    assert "correct" in query
    assert "wrong" in query
    assert params["ticket_id"] == "9846499"
    assert params["expert_email"] == "expert@example.com"
    assert params["expert_name"] == "Example Expert"
    assert params["trace_id"] == "trace-1"
    assert event == {"id": "event-1", "outcome": "wrong"}


@pytest.mark.asyncio
async def test_get_aura_routing_accuracy_uses_latest_routing_event_against_assigned_to():
    session = _FakeSession([{"evaluated": 4, "correct": 3, "accuracy_pct": 75.0}])

    accuracy = await queries.get_aura_routing_accuracy(session)

    query = session.calls[0][0]
    assert "RoutingEvent" in query
    assert "ASSIGNED_TO" in query
    assert "assigned_rel.final" in query
    assert "t.ingest_status = 'promoted'" in query
    assert "aura_suggestion_email" not in query
    assert "ai_suggestion_email" not in query
    assert accuracy == {"evaluated": 4, "correct": 3, "accuracy_pct": 75.0}


@pytest.mark.asyncio
async def test_get_teamwork_routing_mode_defaults_to_manual():
    session = _FakeSession([{}])

    mode = await queries.get_teamwork_routing_mode(session)

    query = session.calls[0][0]
    assert "TeamworkSetting" in query
    assert mode == "manual"


@pytest.mark.asyncio
async def test_set_teamwork_routing_mode_persists_allowed_mode():
    session = _FakeSession([{"mode": "auto_assign"}])

    result = await queries.set_teamwork_routing_mode(session, "auto_assign")

    query, params = session.calls[0]
    assert "TeamworkSetting" in query
    assert "routing_mode" in query
    assert params == {"mode": "auto_assign"}
    assert result == {"mode": "auto_assign"}


@pytest.mark.asyncio
async def test_set_teamwork_routing_mode_rejects_unknown_mode():
    session = _FakeSession()

    with pytest.raises(ValueError):
        await queries.set_teamwork_routing_mode(session, "bad-mode")

    assert session.calls == []


@pytest.mark.asyncio
async def test_has_routing_recommendation_uses_explicit_aggregation_grouping():
    session = _FakeSession([{"has_recommendation": True}])

    has_recommendation = await queries.has_routing_recommendation(session, ticket_id="4093106")

    query, params = session.calls[0]
    assert "WITH t, count(event) AS recommendation_events" in query
    assert "OR recommendation_events > 0 AS has_recommendation" in query
    assert "OR count(event)" not in query
    assert params == {"ticket_id": "4093106"}
    assert has_recommendation is True


@pytest.mark.asyncio
async def test_set_ticket_aura_routing_status_updates_ticket_state():
    session = _FakeSession()

    await queries.set_ticket_aura_routing_status(
        session,
        ticket_id="4093106",
        status="running",
        error=None,
    )

    query, params = session.calls[0]
    assert "SET t.routing_status = $status" in query
    assert "t.aura_routing_error = $error" in query
    assert "t.aura_routing_updated_at" in query
    assert params == {"ticket_id": "4093106", "status": "running", "error": None}


@pytest.mark.asyncio
async def test_set_ticket_aura_routing_status_rejects_unknown_status():
    session = _FakeSession()

    with pytest.raises(ValueError):
        await queries.set_ticket_aura_routing_status(session, ticket_id="4093106", status="bad")

    assert session.calls == []


@pytest.mark.asyncio
async def test_list_stale_aura_routing_tickets_finds_orphaned_running_jobs():
    session = _FakeSession([{"rows": [{"id": "4099107"}]}])

    ticket_ids = await queries.list_stale_aura_routing_tickets(session, stale_minutes=3, limit=10)

    query, params = session.calls[0]
    assert "t.routing_status = 'running'" in query
    assert "coalesce(t.aura_suggestion_email, '') = ''" in query
    assert "HAS_ROUTING_EVENT" in query
    assert (
        "datetime(t.aura_routing_updated_at) < datetime() - duration({minutes: $stale_minutes})"
        in query
    )
    assert params == {"stale_minutes": 3, "limit": 10}
    assert ticket_ids == ["4099107"]
