import asyncio

import pytest

from app.services.aura_tracing import AuraTraceOutcome


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    async def data(self):
        return self._rows

    async def single(self):
        return {"event": {}}


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def run(self, query, **params):
        self.calls.append((query, params))
        if "MATCH (u:User) RETURN u.email AS email, u.name AS name" in query:
            return _FakeResult(
                [
                    {"email": "expert@example.com", "name": "Example Expert"},
                ]
            )
        return _FakeResult()


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_route_aura_persists_recommendation_as_ai_suggestion(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_ticket_full(_session, ticket_id: str):
        assert ticket_id == "123"
        await asyncio.sleep(0)
        return {
            "id": "123",
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        assert subject == "Login issue"
        assert content == "User cannot log in."
        assert client_name == "Acme"
        assert current_ticket_id == "123"
        return {"output": "Recommended based on client history.\nRECOMMENDED: expert@example.com"}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_ticket_full",
        fake_get_ticket_full,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ticket_id"] == "123"
    assert body["expert_email"] == "expert@example.com"
    assert body["expert_name"] == "Example Expert"
    assert "routing_event" in body
    status_updates = [
        params for query, params in session.calls if "SET t.routing_status = $status" in query
    ]
    assert status_updates == [
        {"ticket_id": "123", "status": "running", "error": None},
        {"ticket_id": "123", "status": "suggested", "error": None},
    ]
    persisted = [
        params for query, params in session.calls if "t.aura_suggestion_email = $email" in query
    ]
    assert persisted == [{"id": "123", "email": "expert@example.com", "confidence": "aura"}]
    suggested = [
        params for query, params in session.calls if "t.routing_status = 'suggested'" in query
    ]
    assert suggested == [{"id": "123", "email": "expert@example.com", "confidence": "aura"}]


@pytest.mark.asyncio
async def test_route_aura_persists_compact_trace_metadata(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_ticket_full(_session, ticket_id: str):
        assert ticket_id == "123"
        await asyncio.sleep(0)
        return {
            "id": "123",
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_trace_aura_route_call(call, **kwargs):
        assert kwargs == {
            "ticket_id": "123",
            "subject": "Login issue",
            "content": "User cannot log in.",
            "client_name": "Acme",
        }
        response = await call()
        return AuraTraceOutcome(response=response, trace_id="trace-123", latency_ms=42)

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_ticket_full",
        fake_get_ticket_full,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.trace_aura_route_call",
        fake_trace_aura_route_call,
    )

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 200
    compact_trace_writes = [
        params for query, params in session.calls if "t.aura_trace_id = $trace_id" in query
    ]
    assert compact_trace_writes == [{"id": "123", "trace_id": "trace-123"}]


@pytest.mark.asyncio
async def test_route_aura_uses_client_domain_before_derived_display_name(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_ticket_full(_session, ticket_id: str):
        assert ticket_id == "123"
        await asyncio.sleep(0)
        return {
            "id": "123",
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_name": None,
            "client_domain": "example-staffing.com",
            "client_display_name": "Example Staffing",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        assert client_name == "example-staffing.com"
        await asyncio.sleep(0)
        return {"output": "RECOMMENDED: expert@example.com"}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_ticket_full",
        fake_get_ticket_full,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_route_aura_records_routing_event(client, monkeypatch):
    session = _FakeSession()
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        assert ticket_id == "123"
        await asyncio.sleep(0)
        return {
            "id": "123",
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_trace_aura_route_call(call, **kwargs):
        response = await call()
        return AuraTraceOutcome(response=response, trace_id="trace-123", latency_ms=42)

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "outcome": "correct"}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_ticket_full",
        fake_get_ticket_full,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.trace_aura_route_call",
        fake_trace_aura_route_call,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 200
    assert event_calls == [
        {
            "ticket_id": "123",
            "expert_email": "expert@example.com",
            "expert_name": "Example Expert",
            "confidence": "aura",
            "mode": "manual",
            "action": "stored",
            "trace_id": "trace-123",
        }
    ]
    assert resp.json()["routing_event"] == {"id": "event-123", "outcome": "correct"}


@pytest.mark.asyncio
async def test_route_aura_no_expert_is_retryable_failure_with_event(client, monkeypatch):
    session = _FakeSession()
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "I cannot identify a specific expert from the supplied context."}

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "outcome": "upstream_error"}

    async def fake_trace_aura_route_call(call, **kwargs):
        response = await call()
        return AuraTraceOutcome(response=response, trace_id="trace-123", latency_ms=42)

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.services.aura_routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.trace_aura_route_call",
        fake_trace_aura_route_call,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 502
    assert resp.json()["detail"] == "Aura agent did not return a recommended expert email"
    trace_id = event_calls[0].pop("trace_id")
    assert trace_id == "trace-123"
    assert event_calls == [
        {
            "ticket_id": "123",
            "expert_email": None,
            "expert_name": None,
            "confidence": "aura",
            "mode": "manual",
            "action": "no_recommendation",
        }
    ]
    status_updates = [
        params for query, params in session.calls if "SET t.routing_status = $status" in query
    ]
    assert status_updates == [
        {"ticket_id": "123", "status": "running", "error": None},
    ]
    no_recommendation = [
        params
        for query, params in session.calls
        if "t.routing_status = 'no_recommendation'" in query
    ]
    assert no_recommendation == [{"id": "123"}]
    cleared = [query for query, _params in session.calls if "REMOVE t.aura_suggestion_email" in query]
    assert len(cleared) == 1


@pytest.mark.asyncio
async def test_automated_route_aura_uses_configured_teamwork_routing_mode(client, monkeypatch):
    session = _FakeSession()
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_get_teamwork_routing_mode(_session):
        return "auto_comment"

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "mode": kwargs["mode"]}

    async def fake_post_private_note(**kwargs):
        return {"ok": True}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_ticket_full",
        fake_get_ticket_full,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )
    monkeypatch.setattr("app.services.aura_routing.tw.post_private_note", fake_post_private_note)

    from app.services import aura_routing

    result = await aura_routing.route_ticket_with_aura_automated("123")

    assert result["ticket_id"] == "123"
    assert event_calls[0]["mode"] == "auto_comment"


@pytest.mark.asyncio
async def test_manual_route_aura_ignores_auto_assign_mode(client, monkeypatch):
    session = _FakeSession()
    assign_calls = []
    note_calls = []
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_get_teamwork_routing_mode(_session):
        return "auto_assign"

    async def fake_assign_ticket_to_expert(**kwargs):
        assign_calls.append(kwargs)
        return {"ok": True}

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "mode": kwargs["mode"], "action": kwargs["action"]}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.services.aura_routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.tw.assign_ticket_to_expert", fake_assign_ticket_to_expert
    )
    monkeypatch.setattr("app.services.aura_routing.tw.post_private_note", fake_post_private_note)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )

    resp = await client.post("/api/import/tickets/123/route-aura")

    assert resp.status_code == 200
    assert assign_calls == []
    assert note_calls == []
    assert event_calls[0]["mode"] == "manual"
    assert event_calls[0]["action"] == "stored"


@pytest.mark.asyncio
async def test_route_aura_auto_comment_posts_private_note_and_records_action(client, monkeypatch):
    session = _FakeSession()
    note_calls = []
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_get_teamwork_routing_mode(_session):
        return "auto_comment"

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "action": kwargs["action"]}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.services.aura_routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr("app.services.aura_routing.tw.post_private_note", fake_post_private_note)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )

    from app.services import aura_routing

    result = await aura_routing.route_ticket_with_aura_automated("123")

    assert result["ticket_id"] == "123"
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Korca Aura suggests Example Expert (expert@example.com) for this ticket.",
            "mention_email": "expert@example.com",
            "mention_name": "Example Expert",
        }
    ]
    assert event_calls[0]["action"] == "posted_comment"


@pytest.mark.asyncio
async def test_route_aura_auto_assign_assigns_expert_and_records_action(client, monkeypatch):
    session = _FakeSession()
    assign_calls = []
    note_calls = []
    event_calls = []
    assignment_updates = []
    finalized = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Login issue",
            "request_content": "User cannot log in.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: expert@example.com"}

    async def fake_get_teamwork_routing_mode(_session):
        return "auto_assign"

    async def fake_assign_ticket_to_expert(**kwargs):
        assign_calls.append(kwargs)
        return {"ok": True}

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "action": kwargs["action"]}

    status_updates = []

    async def fake_set_ticket_aura_routing_status(_session, **kwargs):
        status_updates.append(kwargs)

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_upsert_teamwork_assigned_to(_session, **kwargs):
        assignment_updates.append(kwargs)
        return "assigned"

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        finalized.append(ticket_id)
        return {"outcome": "correct"}

    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.services.aura_routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.tw.assign_ticket_to_expert", fake_assign_ticket_to_expert
    )
    monkeypatch.setattr("app.services.aura_routing.tw.post_private_note", fake_post_private_note)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.set_ticket_aura_routing_status",
        fake_set_ticket_aura_routing_status,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.upsert_teamwork_assigned_to",
        fake_upsert_teamwork_assigned_to,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )

    from app.services import aura_routing

    result = await aura_routing.route_ticket_with_aura_automated("123")

    assert result["ticket_id"] == "123"
    assert assign_calls == [{"ticket_id": 123, "expert_email": "expert@example.com"}]
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Ticket was assigned to Example Expert.",
            "mention_email": "expert@example.com",
            "mention_name": "Example Expert",
        }
    ]
    assert event_calls[0]["action"] == "assigned"
    assert status_updates[-1] == {"ticket_id": "123", "status": "suggested", "error": None}
    assert assignment_updates == [
        {
            "ticket_id": "123",
            "agent_email": "expert@example.com",
            "agent_name": "Example Expert",
            "final": False,
            "source": "korca_assignment",
        }
    ]
    assert finalized == ["123"]


@pytest.mark.asyncio
async def test_route_aura_auto_assign_posts_assignment_note_for_fallback_expert(
    client, monkeypatch
):
    session = _FakeSession()
    assign_calls = []
    note_calls = []
    event_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "subject": "Website changes",
            "request_content": "Please update the website.",
            "client_display_name": "Acme",
        }

    async def fake_route_with_aura_agent(
        subject: str,
        content: str,
        client_name: str,
        current_ticket_id: str,
    ):
        return {"output": "RECOMMENDED: suggested.expert@example.com"}

    async def fake_get_teamwork_routing_mode(_session):
        return "auto_assign"

    async def fake_assign_ticket_to_expert(**kwargs):
        assign_calls.append(kwargs)
        if kwargs["expert_email"] == "suggested.expert@example.com":
            raise ValueError("Teamwork agent not found for suggested.expert@example.com")
        return {"ok": True}

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_record_aura_routing_event(_session, **kwargs):
        event_calls.append(kwargs)
        return {"id": "event-123", "action": kwargs["action"]}

    async def fake_upsert_teamwork_assigned_to(_session, **kwargs):
        return "assigned"

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        return {"outcome": "wrong"}

    monkeypatch.setattr(
        "app.services.aura_routing.settings.teamwork_fallback_agent_email", "staging@example.com"
    )
    monkeypatch.setattr(
        "app.services.aura_routing.settings.teamwork_staging_expert_email", "staging@example.com"
    )
    monkeypatch.setattr(
        "app.services.aura_routing.settings.teamwork_staging_expert_name", "Staging Expert"
    )
    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.services.aura_routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )
    monkeypatch.setattr("app.services.aura_routing.route_with_aura_agent", fake_route_with_aura_agent)
    monkeypatch.setattr(
        "app.services.aura_routing.tw.assign_ticket_to_expert", fake_assign_ticket_to_expert
    )
    monkeypatch.setattr("app.services.aura_routing.tw.post_private_note", fake_post_private_note)
    monkeypatch.setattr(
        "app.services.aura_routing.queries.record_aura_routing_event",
        fake_record_aura_routing_event,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.upsert_teamwork_assigned_to",
        fake_upsert_teamwork_assigned_to,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )

    from app.services import aura_routing

    result = await aura_routing.route_ticket_with_aura_automated("123")

    assert result["ticket_id"] == "123"
    assert assign_calls == [
        {"ticket_id": 123, "expert_email": "suggested.expert@example.com"},
        {"ticket_id": 123, "expert_email": "staging@example.com"},
    ]
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Ticket was assigned to Staging Expert.",
            "mention_email": "staging@example.com",
            "mention_name": "Staging Expert",
        }
    ]
    assert event_calls[0]["action"] == "assigned"
