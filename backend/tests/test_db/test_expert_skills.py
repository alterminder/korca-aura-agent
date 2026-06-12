import pytest

from app.db import queries


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def data(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    async def run(self, query, **params):
        self.calls.append((query, params))
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_get_expert_ticket_summaries_uses_assigned_teamwork_closed_tickets():
    session = _FakeSession(rows=[{"content": "Customer cannot configure DNS."}])

    summaries = await queries.get_expert_ticket_summaries(session, "user_example")

    query, params = session.calls[0]
    assert "ASSIGNED_TO" in query
    assert "source_system = 'teamwork'" in query
    assert "toLower(coalesce(t.status, '')) IN ['closed', 'solved', 'resolved']" in query
    assert params == {"id": "user_example", "limit": 40}
    assert summaries == ["Customer cannot configure DNS."]


@pytest.mark.asyncio
async def test_list_teamwork_experts_for_skill_generation_uses_assigned_closed_history():
    session = _FakeSession(
        rows=[
            {
                "id": "user_example",
                "name": "Example Expert",
                "email": "expert@example.com",
                "ticket_count": 12,
            }
        ]
    )

    experts = await queries.list_teamwork_experts_for_skill_generation(session)

    query, _params = session.calls[0]
    assert "ASSIGNED_TO" in query
    assert "source_system = 'teamwork'" in query
    assert "toLower(coalesce(t.status, '')) IN ['closed', 'solved', 'resolved']" in query
    assert "HAS_SKILL" in query
    assert experts == [
        {
            "id": "user_example",
            "name": "Example Expert",
            "email": "expert@example.com",
            "ticket_count": 12,
        }
    ]
