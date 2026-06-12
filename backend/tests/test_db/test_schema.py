import pytest

from app.db.schema import init_schema


class _FakeResult:
    pass


class _FakeSession:
    def __init__(self):
        self.queries = []

    async def run(self, query, **params):
        self.queries.append(query)
        return _FakeResult()


@pytest.mark.asyncio
async def test_init_schema_seeds_routing_event_tokens_without_persistent_nodes():
    session = _FakeSession()

    await init_schema(session)

    joined = "\n".join(session.queries)
    assert "RoutingEvent" in joined
    assert "HAS_ROUTING_EVENT" in joined
    assert "RECOMMENDED_EXPERT" in joined
    assert "suggested_email" in joined
    assert "DETACH DELETE" in joined
