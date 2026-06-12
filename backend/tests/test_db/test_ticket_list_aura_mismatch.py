import pytest

from app.db import queries


class _FakeResult:
    async def data(self):
        return []

    async def single(self):
        return {"n": 0}


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def run(self, query, **params):
        self.calls.append((query, params))
        return _FakeResult()


@pytest.mark.asyncio
async def test_list_tickets_mismatch_uses_latest_routing_event():
    session = _FakeSession()

    await queries.list_tickets(session, source_system="teamwork", mismatch_only=True)

    query = session.calls[0][0]
    assert "OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)" in query
    assert "HAS_ROUTING_EVENT" in query
    assert "latest_event.suggested_email" in query
    assert "latest_event.suggested_email <> assigned.email" in query
    assert "AS is_mismatch" in query
    assert "request_preview: substring(coalesce(t.request_content, t.preview, ''), 0, 500)" in query
    assert "resolved.email <> routed.email" not in query
    assert "t.aura_suggestion_email <> coalesce" not in query


@pytest.mark.asyncio
async def test_count_tickets_filtered_mismatch_uses_latest_routing_event():
    session = _FakeSession()

    await queries.count_tickets_filtered(
        session,
        source_system="teamwork",
        mismatch_only=True,
    )

    query = session.calls[0][0]
    assert "OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)" in query
    assert "HAS_ROUTING_EVENT" in query
    assert "latest_event.suggested_email" in query
    assert "latest_event.suggested_email <> assigned.email" in query
    assert "AS is_mismatch" in query
    assert "resolved.email <> routed.email" not in query
    assert "t.aura_suggestion_email <> coalesce" not in query


@pytest.mark.asyncio
async def test_get_ticket_full_prefers_assigned_to_for_assigned_expert_fields():
    class _TicketResult:
        async def single(self):
            return {"ticket": {"id": "123", "routing_suggestions": None}}

    class _TicketSession(_FakeSession):
        async def run(self, query, **params):
            self.calls.append((query, params))
            return _TicketResult()

    session = _TicketSession()

    await queries.get_ticket_full(session, "123")

    query = session.calls[0][0]
    assert "OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)" in query
    assert "agent_name: assigned.name" in query
    assert "agent_email: assigned.email" in query
