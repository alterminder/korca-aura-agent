import pytest

from app.db import queries


class _FakeResult:
    def __init__(self, record=None):
        self._record = record or {}

    async def single(self):
        return self._record

    async def consume(self):
        return None


class _FakeSession:
    def __init__(self, records=None):
        self.calls = []
        self._records = list(records or [])

    async def run(self, query, **params):
        self.calls.append((query, params))
        record = self._records.pop(0) if self._records else {}
        return _FakeResult(record)


@pytest.mark.asyncio
async def test_get_teamwork_update_sync_state_reads_named_sync_state():
    session = _FakeSession(
        [
            {
                "state": {
                    "source": "teamwork",
                    "name": "ticket_updates",
                    "cursor": "2026-05-21T10:00:00Z",
                    "status": "ok",
                }
            }
        ]
    )

    state = await queries.get_teamwork_update_sync_state(session)

    query = session.calls[0][0]
    assert "SyncState" in query
    assert 'source: "teamwork"' in query
    assert 'name: "ticket_updates"' in query
    assert state == {
        "source": "teamwork",
        "name": "ticket_updates",
        "cursor": "2026-05-21T10:00:00Z",
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_bootstrap_teamwork_update_sync_state_sets_cursor_to_now_without_replay():
    session = _FakeSession(
        [
            {
                "state": {
                    "source": "teamwork",
                    "name": "ticket_updates",
                    "cursor": "2026-05-21T12:00:00Z",
                    "status": "ok",
                }
            }
        ]
    )

    state = await queries.bootstrap_teamwork_update_sync_state(
        session,
        cursor="2026-05-21T12:00:00Z",
    )

    query, params = session.calls[0]
    assert "MERGE (s:SyncState" in query
    assert "initialized_at" in query
    assert params["cursor"] == "2026-05-21T12:00:00Z"
    assert state["cursor"] == "2026-05-21T12:00:00Z"


@pytest.mark.asyncio
async def test_upsert_teamwork_assignment_skips_protected_historical_assignment():
    session = _FakeSession([{"result": "protected"}])

    result = await queries.upsert_teamwork_assigned_to(
        session,
        ticket_id="9846499",
        agent_email="wrong@example.com",
        agent_name="Wrong Expert",
        final=True,
    )

    query, params = session.calls[0]
    assert "ASSIGNED_TO" in query
    assert "protected, false) = true" in query
    assert "DELETE rel" in query
    assert params["ticket_id"] == "9846499"
    assert params["agent_email"] == "wrong@example.com"
    assert result == "protected"


@pytest.mark.asyncio
async def test_upsert_teamwork_assignment_can_clear_stale_protected_staged_assignment():
    session = _FakeSession([{"result": "cleared"}])

    result = await queries.upsert_teamwork_assigned_to(
        session,
        ticket_id="4093106",
        agent_email=None,
        agent_name=None,
        final=False,
    )

    query, params = session.calls[0]
    assert "effective_protected" in query
    assert "coalesce(t.ingest_status, '') = 'promoted'" in query
    assert "source = 'historical_correction'" in query
    assert params["ticket_id"] == "4093106"
    assert params["agent_email"] is None
    assert result == "cleared"


@pytest.mark.asyncio
async def test_upsert_teamwork_assignment_normalizes_agent_email():
    session = _FakeSession([{"result": "assigned"}])

    result = await queries.upsert_teamwork_assigned_to(
        session,
        ticket_id="4093106",
        agent_email="  Agent@Example.COM ",
        agent_name="Ann Bee",
    )

    _query, params = session.calls[0]
    assert params["agent_email"] == "agent@example.com"
    assert result == "assigned"


@pytest.mark.asyncio
async def test_reassign_assigned_to_updates_assignment_ground_truth():
    session = _FakeSession([{"n": 1}, {}])

    ok = await queries.reassign_assigned_to(
        session,
        ticket_id="9846499",
        expert_email="correct@example.com",
        expert_name="Correct Expert",
    )

    first_query, _first_params = session.calls[0]
    second_query, second_params = session.calls[1]
    assert ok is True
    assert "ASSIGNED_TO" in first_query
    assert "DELETE rel" in first_query
    assert "MERGE (u)-[a:ASSIGNED_TO]->(t)" in second_query
    assert "a.protected = $protected" in second_query
    assert "a.final = $final" in second_query
    assert 'a.source = "korca"' in second_query
    assert second_params["email"] == "correct@example.com"
    assert second_params["name"] == "Correct Expert"
    assert second_params["protected"] is True
    assert second_params["final"] is True


@pytest.mark.asyncio
async def test_complete_teamwork_update_sync_state_records_counts_and_advances_cursor():
    session = _FakeSession(
        [
            {
                "state": {
                    "source": "teamwork",
                    "name": "ticket_updates",
                    "cursor": "2026-05-21T12:30:00Z",
                    "status": "ok",
                    "processed": 2,
                }
            }
        ]
    )

    state = await queries.complete_teamwork_update_sync_state(
        session,
        cursor="2026-05-21T12:30:00Z",
        status="ok",
        counts={"processed": 2, "imported": 1, "updated": 1, "protected_skipped": 0, "failed": 0},
        error=None,
    )

    query, params = session.calls[0]
    assert "last_run_at" in query
    assert "processed" in query
    assert params["cursor"] == "2026-05-21T12:30:00Z"
    assert params["processed"] == 2
    assert state["cursor"] == "2026-05-21T12:30:00Z"


@pytest.mark.asyncio
async def test_complete_teamwork_update_sync_state_records_failed_ticket_metadata():
    session = _FakeSession(
        [
            {
                "state": {
                    "source": "teamwork",
                    "name": "ticket_updates",
                    "cursor": "2026-05-21T12:30:00Z",
                    "status": "partial",
                    "failed_ticket_ids": ["555"],
                    "last_failed_ticket_errors": ["555: database query failed"],
                }
            }
        ]
    )

    state = await queries.complete_teamwork_update_sync_state(
        session,
        cursor="2026-05-21T12:30:00Z",
        status="partial",
        counts={"processed": 1, "imported": 0, "updated": 0, "protected_skipped": 0, "failed": 1},
        error="1 ticket(s) failed",
        failed_ticket_ids=["555"],
        failed_ticket_errors=["555: database query failed"],
    )

    query, params = session.calls[0]
    assert "failed_ticket_ids" in query
    assert "last_failed_ticket_errors" in query
    assert params["failed_ticket_ids"] == ["555"]
    assert params["failed_ticket_errors"] == ["555: database query failed"]
    assert state["failed_ticket_ids"] == ["555"]


@pytest.mark.asyncio
async def test_teamwork_auto_sync_settings_default_disabled():
    session = _FakeSession([{}])

    settings = await queries.get_teamwork_auto_sync_settings(session)

    query = session.calls[0][0]
    assert "TeamworkSetting" in query
    assert "auto_sync_enabled" in query
    assert settings == {"enabled": False, "interval_seconds": 60}


@pytest.mark.asyncio
async def test_set_teamwork_auto_sync_settings_persists_allowed_interval():
    session = _FakeSession([{"enabled": True, "interval_seconds": 300}])

    settings = await queries.set_teamwork_auto_sync_settings(
        session,
        enabled=True,
        interval_seconds=300,
    )

    query, params = session.calls[0]
    assert "auto_sync_enabled" in query
    assert "auto_sync_interval_seconds" in query
    assert params == {"enabled": True, "interval_seconds": 300}
    assert settings == {"enabled": True, "interval_seconds": 300}


@pytest.mark.asyncio
async def test_set_teamwork_auto_sync_settings_rejects_unknown_interval():
    session = _FakeSession()

    with pytest.raises(ValueError):
        await queries.set_teamwork_auto_sync_settings(
            session,
            enabled=True,
            interval_seconds=90,
        )

    assert session.calls == []


@pytest.mark.asyncio
async def test_finalize_latest_routing_event_compares_latest_suggestion_to_assigned_to():
    session = _FakeSession([{"event": {"id": "event-1", "outcome": "wrong"}}])

    event = await queries.finalize_latest_routing_event_for_ticket(session, ticket_id="123")

    query, params = session.calls[0]
    assert "RoutingEvent" in query
    assert "ASSIGNED_TO" in query
    assert "correct" in query
    assert "wrong" in query
    assert params == {"ticket_id": "123"}
    assert event == {"id": "event-1", "outcome": "wrong"}
