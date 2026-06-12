import asyncio
import json
from typing import ClassVar, get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock

import pytest

from app.api.routes.routing import _latest_aura_suggestion
from app.services.aura_routing import _aura_suggestion_note
from app.services.teamwork_sync import _extract_ticket

TEAMWORK_IMPORT_ROUTE = "app.api.routes.teamwork_import"
_ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep


@pytest.fixture(autouse=True)
def _default_no_full_import_running(monkeypatch):
    async def fake_running():
        return await _async_value(False)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.is_full_import_running", fake_running)


async def _async_value(value):
    await _ORIGINAL_ASYNCIO_SLEEP(0)
    return value


async def _fake_false(*args, **kwargs):
    return await _async_value(False)


async def _fake_none(*args, **kwargs):
    return await _async_value(None)


def _patch_reimport_infra(monkeypatch, session, ticket_payload, upsert_calls, gate_calls):
    """Patch the common reimport infrastructure.

    Each test patches summarize_ticket and embed_query separately to control
    qualifying vs non-qualifying behaviour for its specific ticket state.
    """

    async def _fetch_full(ticket_id: int):
        assert ticket_id == ticket_payload["id"]
        return await _async_value(ticket_payload)

    async def _fetch_threads(ticket_id: int):
        assert ticket_id == ticket_payload["id"]
        return await _async_value([])

    async def _upsert_ticket(_session, ticket, **kwargs):
        upsert_calls.append(ticket)
        return await _async_value(None)

    async def _gate(_session, ticket, **kwargs):
        gate_calls.append(
            {
                "ticket_id": str(ticket["id"]),
                "require_assignee": kwargs.get("require_assignee"),
                "require_closed": kwargs.get("require_closed"),
            }
        )
        return await _async_value(None)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.tw.fetch_ticket_full", _fetch_full)
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.tw.fetch_ticket_threads", _fetch_threads)
    # _persist_imported_teamwork_ticket lives in teamwork_sync — patch its queries there
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", _upsert_ticket)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", _fake_none
    )
    monkeypatch.setattr("app.services.teamwork_sync.gate_and_persist_ticket", _gate)


def _patch_sync_now_infra(monkeypatch, session, *, completed=None):
    """Patch the invariant sync-now infrastructure.

    Applies Redis lock, db context, a standard 10:00 cursor, and false/None
    defaults for per-ticket DB lookups. Tests override individual patches
    after calling this for anything that needs to vary.
    """

    async def _get_state(_session):
        return await _async_value({"cursor": "2026-05-21T10:00:00Z", "status": "ok"})

    async def _complete(_session, **kwargs):
        await _async_value(None)
        if completed is not None:
            completed.append(kwargs)
        return {"cursor": kwargs["cursor"], "status": kwargs["status"]}

    monkeypatch.setattr("app.services.teamwork_sync.Redis", _FakeRedis)
    monkeypatch.setattr("app.services.teamwork_sync.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_teamwork_update_sync_state", _get_state
    )
    monkeypatch.setattr("app.services.teamwork_sync.queries.has_protected_assigned_to", _fake_false)
    monkeypatch.setattr("app.services.teamwork_sync.queries.ticket_exists", _fake_false)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.has_routing_recommendation", _fake_false
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_ticket_processing_payload", _fake_none
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.complete_teamwork_update_sync_state", _complete
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.finalize_latest_routing_event_for_ticket", _fake_none
    )


class _FakeResult:
    pass


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def run(self, query, **params):
        await _async_value(None)
        self.calls.append((query, params))
        return _FakeResult()


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return await _async_value(self._session)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


class _FakeRedis:
    """Minimal Redis stub — lock is available (set returns truthy)."""

    instances: ClassVar[list["_FakeRedis"]] = []

    def __init__(self):
        self.values = {}
        self.eval_calls = []
        self.deleted = []

    @classmethod
    def from_url(cls, *a, **kw):
        instance = cls()
        cls.instances.append(instance)
        return instance

    async def set(self, key, value, **kw):
        await _async_value(None)
        if kw.get("nx") and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key):
        await _async_value(None)
        return self.values.get(key)

    async def delete(self, key):
        await _async_value(None)
        self.deleted.append(key)
        self.values.pop(key, None)

    async def exists(self, key):
        await _async_value(None)
        return 1 if key in self.values else 0

    async def eval(self, script, numkeys, key, token):
        await _async_value(None)
        self.eval_calls.append((script, numkeys, key, token))
        if self.values.get(key) == token:
            self.values.pop(key, None)
            return 1
        return 0

    async def __aenter__(self):
        return await _async_value(self)

    async def __aexit__(self, *a):
        await _async_value(None)


class _FakeRedisLocked(_FakeRedis):
    """Minimal Redis stub — lock is already held (set returns None)."""

    async def set(self, key, value, **kw):
        return await _async_value(None)

    async def exists(self, key):
        return await _async_value(1)  # lock is held


def test_extract_ticket_ignores_teamwork_private_notes_for_request_content():
    ticket = _extract_ticket(
        {
            "id": 4093106,
            "subject": "Website font",
            "preview": "Customer reports the website font changed.",
            "status": "active",
            "assignedTo": {},
            "company": {"name": "Example Education"},
        },
        {"id": 4093106},
        [
            {
                "id": 1,
                "type": "note",
                "threadType": {"id": 3, "name": "note"},
                "body": "Korca Aura suggests suggested.expert@example.com",
            },
            {
                "id": 2,
                "type": "message",
                "threadType": {"id": 1, "name": "message"},
                "body": "The website font looks incorrect.",
            },
        ],
    )

    assert "Korca Aura suggests" not in ticket["content"]
    assert "Korca Aura suggests" not in ticket["raw_content"]
    assert ticket["content"] == "Website font\n\nThe website font looks incorrect."


def test_extract_ticket_normalizes_agent_email():
    ticket = _extract_ticket(
        {
            "id": 4093107,
            "subject": "Help",
            "assignedTo": {"email": "  Agent@Example.COM ", "firstName": "Ann", "lastName": "Bee"},
        },
        {},
        [],
    )

    assert ticket["agent_email"] == "agent@example.com"
    assert ticket["agent_name"] == "Ann Bee"


def test_aura_suggestion_note_uses_name_and_email_without_duplicate_fallback():
    assert (
        _aura_suggestion_note("Suggested Expert", "suggested.expert@example.com")
        == "Korca Aura suggests Suggested Expert (suggested.expert@example.com) for this ticket."
    )
    assert (
        _aura_suggestion_note(None, "suggested.expert@example.com")
        == "Korca Aura suggests suggested.expert@example.com for this ticket."
    )


def test_latest_aura_suggestion_falls_back_to_routed_name_when_event_name_missing():
    email, name = _latest_aura_suggestion(
        {
            "latest_aura_suggestion_email": None,
            "latest_aura_suggestion_name": None,
            "aura_suggestion_email": "suggested.expert@example.com",
            "routed_to_email": "suggested.expert@example.com",
            "routed_to_name": "Suggested Expert",
            "routing_suggestions": [
                {
                    "email": "suggested.expert@example.com",
                    "name": "Suggested Expert",
                }
            ],
        }
    )

    assert email == "suggested.expert@example.com"
    assert name == "Suggested Expert"


def test_latest_aura_suggestion_uses_routing_suggestion_name_without_routed_edge():
    email, name = _latest_aura_suggestion(
        {
            "aura_suggestion_email": "suggested.expert@example.com",
            "routing_suggestions": [
                {
                    "email": "suggested.expert@example.com",
                    "name": "Suggested Expert",
                }
            ],
        }
    )

    assert email == "suggested.expert@example.com"
    assert name == "Suggested Expert"


_CLOSED_FONT_TICKET = {
    "id": 4093106,
    "subject": "Website font",
    "preview": "Font issue",
    "status": "Closed",
    "updatedAt": "2026-05-22T20:40:15Z",
    "createdAt": "2026-05-11T22:37:11Z",
    "assignedTo": {"email": "expert@example.com", "firstName": "Example", "lastName": "Expert"},
    "company": {"name": "Example Education"},
    "threads": [{"id": 1, "threadType": "message", "body": "The website font looks incorrect."}],
}

_OPEN_FONT_TICKET = {
    **_CLOSED_FONT_TICKET,
    "status": "Waiting on customer",
    "assignedTo": {},
}


@pytest.mark.asyncio
async def test_reimport_teamwork_ticket_falls_back_to_request_content_when_summary_fails(
    client, monkeypatch
):
    session = _FakeSession()
    upsert_calls: list = []
    gate_calls: list = []

    _patch_reimport_infra(monkeypatch, session, _CLOSED_FONT_TICKET, upsert_calls, gate_calls)
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(side_effect=RuntimeError("Gemini unavailable")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query", AsyncMock(return_value=[0.1, 0.2, 0.3])
    )

    resp = await client.post("/api/import/teamwork/tickets/4093106/reimport")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert upsert_calls[0]["request_content"] == "Website font\n\nThe website font looks incorrect."
    assert upsert_calls[0]["content"] == "Website font\n\nThe website font looks incorrect."
    assert upsert_calls[0]["embedding"] == [0.1, 0.2, 0.3]
    assert gate_calls == [
        {"ticket_id": "4093106", "require_assignee": True, "require_closed": True}
    ]


@pytest.mark.asyncio
async def test_reimport_open_teamwork_ticket_is_persisted_without_embedding(client, monkeypatch):
    session = _FakeSession()
    upsert_calls: list = []
    gate_calls: list = []

    _patch_reimport_infra(monkeypatch, session, _OPEN_FONT_TICKET, upsert_calls, gate_calls)
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(side_effect=AssertionError("Open tickets must not be summarized")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query",
        AsyncMock(side_effect=AssertionError("Open tickets must not be embedded")),
    )

    resp = await client.post("/api/import/teamwork/tickets/4093106/reimport")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert upsert_calls[0]["request_content"] == "Website font\n\nThe website font looks incorrect."
    assert upsert_calls[0]["content"] == "Website font\n\nThe website font looks incorrect."
    assert upsert_calls[0]["embedding"] is None
    assert gate_calls == [
        {"ticket_id": "4093106", "require_assignee": True, "require_closed": True}
    ]


@pytest.mark.asyncio
async def test_persist_imported_teamwork_ticket_creates_assigned_to_ground_truth(monkeypatch):
    from app.services import teamwork_sync

    session = _FakeSession()
    calls = []

    async def fake_upsert_ticket(_session, ticket):
        calls.append(("upsert", ticket["id"]))

    async def fake_upsert_assignment(_session, **kwargs):
        calls.append(("assigned", kwargs))
        return "assigned"

    async def fake_gate(_session, ticket, **kwargs):
        calls.append(("gate", kwargs, ticket["id"]))

    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", fake_upsert_assignment
    )
    monkeypatch.setattr("app.services.teamwork_sync.gate_and_persist_ticket", fake_gate)

    await teamwork_sync._persist_imported_teamwork_ticket(
        session,
        {
            "id": 4093106,
            "status": "closed",
            "agent_email": "expert@example.com",
            "agent_name": "Example Expert",
        },
    )

    assert calls == [
        ("upsert", 4093106),
        (
            "assigned",
            {
                "ticket_id": "4093106",
                "agent_email": "expert@example.com",
                "agent_name": "Example Expert",
                "final": True,
                "protected": True,
                "source": "teamwork_import",
            },
        ),
        ("gate", {"require_assignee": True, "require_closed": True}, 4093106),
    ]


@pytest.mark.asyncio
async def test_reassign_ticket_updates_graph_assignment_without_teamwork(client, monkeypatch):
    session = _FakeSession()
    reassigned = []
    finalized = []

    async def fake_reassign_assigned_to(
        _session,
        ticket_id: str,
        expert_email: str,
        expert_name: str,
        protected: bool = True,
        final: bool = True,
    ):
        reassigned.append(
            {
                "ticket_id": ticket_id,
                "expert_email": expert_email,
                "expert_name": expert_name,
                "protected": protected,
                "final": final,
            }
        )
        return True

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        finalized.append(ticket_id)
        return {"outcome": "wrong"}

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {"id": ticket_id, "ingest_status": "promoted"}

    monkeypatch.setattr("app.api.routes.tickets.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.api.routes.tickets.queries.reassign_assigned_to", fake_reassign_assigned_to
    )
    monkeypatch.setattr(
        "app.api.routes.tickets.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )
    monkeypatch.setattr("app.api.routes.tickets.queries.get_ticket_full", fake_get_ticket_full)

    resp = await client.post(
        "/api/import/tickets/123/reassign",
        json={"expert_email": "correct@example.com", "expert_name": "Correct Expert"},
    )

    assert resp.status_code == 200
    assert reassigned == [
        {
            "ticket_id": "123",
            "expert_email": "correct@example.com",
            "expert_name": "Correct Expert",
            "protected": True,
            "final": True,
        }
    ]
    assert finalized == ["123"]


@pytest.mark.asyncio
async def test_reassign_open_staged_ticket_stores_overwritable_assignment(client, monkeypatch):
    session = _FakeSession()
    reassigned = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "ingest_status": "staged",
            "status": "Waiting on customer",
        }

    async def fake_reassign_assigned_to(
        _session,
        ticket_id: str,
        expert_email: str,
        expert_name: str,
        protected: bool = True,
        final: bool = True,
    ):
        reassigned.append(
            {
                "ticket_id": ticket_id,
                "expert_email": expert_email,
                "expert_name": expert_name,
                "protected": protected,
                "final": final,
            }
        )
        return True

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        return {"outcome": "correct"}

    monkeypatch.setattr("app.api.routes.tickets.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.tickets.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.api.routes.tickets.queries.reassign_assigned_to", fake_reassign_assigned_to
    )
    monkeypatch.setattr(
        "app.api.routes.tickets.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )

    resp = await client.post(
        "/api/import/tickets/4093106/reassign",
        json={"expert_email": "suggested.expert@example.com", "expert_name": "Suggested Expert"},
    )

    assert resp.status_code == 200
    assert reassigned == [
        {
            "ticket_id": "4093106",
            "expert_email": "suggested.expert@example.com",
            "expert_name": "Suggested Expert",
            "protected": False,
            "final": False,
        }
    ]


@pytest.mark.asyncio
async def test_ai_accuracy_endpoint_uses_aura_routing_events(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_aura_routing_accuracy(_session):
        return {"evaluated": 4, "correct": 3, "accuracy_pct": 75.0}

    monkeypatch.setattr("app.api.routes.evaluation.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.api.routes.evaluation.queries.get_aura_routing_accuracy",
        fake_get_aura_routing_accuracy,
    )

    resp = await client.get("/api/import/routing/ai-accuracy")

    assert resp.status_code == 200
    assert resp.json() == {"evaluated": 4, "correct": 3, "accuracy_pct": 75.0}


@pytest.mark.asyncio
async def test_promote_ticket_rejects_open_ticket(client, monkeypatch):
    session = _FakeSession()
    promoted = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "status": "Waiting on customer",
            "agent_email": "expert@example.com",
            "assigned_to_email": "expert@example.com",
        }

    async def fake_set_ticket_ingest_status(*args, **kwargs):
        promoted.append((args, kwargs))

    monkeypatch.setattr("app.api.routes.tickets.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.tickets.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.api.routes.tickets.queries.set_ticket_ingest_status",
        fake_set_ticket_ingest_status,
    )

    resp = await client.post("/api/import/tickets/4093106/promote")

    assert resp.status_code == 409
    assert "closed" in resp.json()["detail"].lower()
    assert promoted == []


@pytest.mark.asyncio
async def test_promote_ticket_rejects_unassigned_ticket(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "status": "Closed",
            "agent_email": None,
            "assigned_to_email": None,
        }

    monkeypatch.setattr("app.api.routes.tickets.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.tickets.queries.get_ticket_full", fake_get_ticket_full)

    resp = await client.post("/api/import/tickets/4093106/promote")

    assert resp.status_code == 409
    assert "assigned" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_teamwork_routing_mode_endpoint_defaults_to_manual(client, monkeypatch):
    from app.config import settings as _settings

    session = _FakeSession()

    async def fake_get_teamwork_routing_mode(_session):
        return await _async_value("manual")

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "")
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )

    resp = await client.get("/api/import/teamwork/routing-mode")

    assert resp.status_code == 200
    assert resp.json() == {"mode": "manual", "staging_expert_configured": False}


@pytest.mark.asyncio
async def test_get_teamwork_routing_mode_reports_staging_expert_configured(client, monkeypatch):
    from app.config import settings as _settings

    session = _FakeSession()

    async def fake_get_teamwork_routing_mode(_session):
        return await _async_value("manual")

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "staging@example.com")
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.get_teamwork_routing_mode",
        fake_get_teamwork_routing_mode,
    )

    resp = await client.get("/api/import/teamwork/routing-mode")

    assert resp.status_code == 200
    assert resp.json()["staging_expert_configured"] is True


@pytest.mark.asyncio
async def test_set_teamwork_routing_mode_endpoint_persists_mode(client, monkeypatch):
    from app.config import settings as _settings

    session = _FakeSession()

    async def fake_set_teamwork_routing_mode(_session, mode: str):
        assert mode == "auto_comment"
        return await _async_value({"mode": "auto_comment"})

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "staging@example.com")
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.set_teamwork_routing_mode",
        fake_set_teamwork_routing_mode,
    )

    resp = await client.put("/api/import/teamwork/routing-mode", json={"mode": "auto_comment"})

    assert resp.status_code == 200
    assert resp.json() == {"mode": "auto_comment", "staging_expert_configured": True}


@pytest.mark.asyncio
async def test_bootstrap_teamwork_sync_endpoint_initializes_cursor(client, monkeypatch):
    session = _FakeSession()

    async def fake_bootstrap(_session):
        return {
            "source": "teamwork",
            "name": "ticket_updates",
            "cursor": "2026-05-21T12:00:00Z",
            "status": "ok",
        }

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.bootstrap_teamwork_update_sync_state",
        fake_bootstrap,
    )

    resp = await client.post("/api/import/teamwork/sync/bootstrap")

    assert resp.status_code == 200
    assert resp.json()["cursor"] == "2026-05-21T12:00:00Z"


@pytest.mark.asyncio
async def test_teamwork_sync_now_refuses_until_cursor_bootstrapped(client, monkeypatch):
    session = _FakeSession()

    async def fake_get_state(_session):
        return await _async_value(None)

    monkeypatch.setattr("app.services.teamwork_sync.Redis", _FakeRedis)
    monkeypatch.setattr("app.services.teamwork_sync.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_teamwork_update_sync_state",
        fake_get_state,
    )

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 409
    assert "bootstrap" in resp.json()["detail"].lower()

    redis = _FakeRedis.instances[-1]
    assert redis.eval_calls, "sync lock must be released on bootstrap refusal"


@pytest.mark.asyncio
async def test_teamwork_sync_now_fetches_updated_tickets_and_skips_protected_assignments(
    client, monkeypatch
):
    session = _FakeSession()
    upsert_calls = []
    assignment_calls = []
    completed = []
    gate_calls = []
    routing_status_updates = []

    async def fake_fetch_updated_tickets(updated_after: str):
        assert updated_after == "2026-05-21T10:00:00Z"
        return await _async_value(
            [
                {
                    "id": 111,
                    "subject": "Protected old ticket",
                    "preview": "Old preview",
                    "status": "solved",
                    "updatedAt": "2026-05-21T10:05:00Z",
                    "createdAt": "2026-05-01T10:00:00Z",
                    "assignedTo": {
                        "email": "teamwork-wrong@example.com",
                        "firstName": "Wrong",
                        "lastName": "Expert",
                    },
                    "company": {"name": "Acme"},
                    "threads": [{"id": 1, "type": "message", "body": "Please help"}],
                },
                {
                    "id": 222,
                    "subject": "New live ticket",
                    "preview": "Need help",
                    "status": "active",
                    "updatedAt": "2026-05-21T10:06:00Z",
                    "createdAt": "2026-05-21T10:05:00Z",
                    "assignedTo": {
                        "email": "expert@example.com",
                        "firstName": "Example",
                        "lastName": "Expert",
                    },
                    "company": {"name": "Acme"},
                    "threads": [{"id": 1, "type": "message", "body": "Need help with login"}],
                },
            ]
        )

    async def fake_upsert_ticket(_session, ticket):
        upsert_calls.append({"ticket": ticket})
        return await _async_value(None)

    async def fake_upsert_assignment(_session, **kwargs):
        assignment_calls.append(kwargs)
        return await _async_value("assigned")

    async def fake_gate_and_persist_ticket(
        _session, ticket, require_assignee=True, require_closed=False
    ):
        gate_calls.append(
            {
                "ticket_id": str(ticket["id"]),
                "require_assignee": require_assignee,
                "require_closed": require_closed,
            }
        )
        return await _async_value(None)

    async def fake_set_ticket_aura_routing_status(_session, **kwargs):
        routing_status_updates.append(kwargs)
        await asyncio.sleep(0)

    _patch_sync_now_infra(monkeypatch, session, completed=completed)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.has_protected_assigned_to",
        AsyncMock(side_effect=lambda _s, tid: str(tid) == "111"),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.ticket_exists",
        AsyncMock(side_effect=lambda _s, tid: str(tid) == "222"),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", fake_upsert_assignment
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.gate_and_persist_ticket", fake_gate_and_persist_ticket
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(side_effect=AssertionError("Open tickets must not be summarized")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query",
        AsyncMock(side_effect=AssertionError("Open tickets must not be embedded")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.set_ticket_aura_routing_status",
        fake_set_ticket_aura_routing_status,
    )
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}._enqueue_aura_routing_job", lambda _: None)

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 2
    assert body["protected_skipped"] == 1
    assert body["updated"] == 1
    assert [call["ticket"]["id"] for call in upsert_calls] == [222]
    assert upsert_calls[0]["ticket"]["embedding"] is None
    assert assignment_calls == [
        {
            "ticket_id": "222",
            "agent_email": "expert@example.com",
            "agent_name": "Example Expert",
            "final": False,
            "source": "teamwork_sync",
        }
    ]
    assert gate_calls == [{"ticket_id": "222", "require_assignee": True, "require_closed": True}]
    assert routing_status_updates == [
        {"ticket_id": "222", "status": "queued"},
    ]
    assert completed[0]["cursor"] == "2026-05-21T10:06:00Z"


@pytest.mark.asyncio
async def test_teamwork_sync_now_advances_cursor_on_partial_failure(client, monkeypatch):
    session = _FakeSession()
    completed = []

    async def fake_fetch_updated_tickets(updated_after: str):
        return [
            {
                "id": 555,
                "subject": "Updated ticket",
                "preview": "Need help",
                "status": "active",
                "updatedAt": "2026-05-21T10:09:00Z",
                "createdAt": "2026-05-21T10:05:00Z",
                "assignedTo": {},
                "company": {"name": "Acme"},
                "threads": [{"id": 1, "type": "message", "body": "Need help"}],
            },
        ]

    _patch_sync_now_infra(monkeypatch, session, completed=completed)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.has_protected_assigned_to",
        AsyncMock(side_effect=RuntimeError("database query failed")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert body["cursor"] == "2026-05-21T10:09:00Z"
    assert body["failed_ticket_ids"] == ["555"]
    assert body["failed_ticket_errors"] == [{"ticket_id": "555", "error": "database query failed"}]
    assert completed[0]["cursor"] == "2026-05-21T10:09:00Z"
    assert completed[0]["failed_ticket_ids"] == ["555"]
    assert completed[0]["failed_ticket_errors"] == ["555: database query failed"]


@pytest.mark.asyncio
async def test_teamwork_sync_now_does_not_reembed_failed_ticket_after_cursor_advances(
    client, monkeypatch
):
    session = _FakeSession()
    state = {"cursor": "2026-05-21T10:00:00Z", "status": "ok"}
    completed = []
    embed_calls = 0

    failed_ticket = {
        "id": 666,
        "subject": "Write failure ticket",
        "preview": "Need help",
        "status": "closed",
        "updatedAt": "2026-05-21T10:10:00Z",
        "createdAt": "2026-05-21T10:05:00Z",
        "assignedTo": {
            "email": "expert@example.com",
            "firstName": "Example",
            "lastName": "Expert",
        },
        "company": {"name": "Acme"},
        "threads": [{"id": 1, "type": "message", "body": "Need help"}],
    }

    async def fake_fetch_updated_tickets(updated_after: str):
        if updated_after == "2026-05-21T10:00:00Z":
            return await _async_value([failed_ticket])
        return await _async_value([])

    async def fake_embed_query(content, context=None):
        nonlocal embed_calls
        embed_calls += 1
        return await _async_value([0.1, 0.2, 0.3])

    async def fake_upsert_ticket(_session, ticket):
        await asyncio.sleep(0)
        raise RuntimeError("neo4j write failed")

    async def fake_get_state(_session):
        return await _async_value(dict(state))

    async def fake_complete(_session, **kwargs):
        completed.append(kwargs)
        state["cursor"] = kwargs["cursor"]
        state["status"] = kwargs["status"]
        return await _async_value({"cursor": kwargs["cursor"], "status": kwargs["status"]})

    _patch_sync_now_infra(monkeypatch, session)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_teamwork_update_sync_state", fake_get_state
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.complete_teamwork_update_sync_state", fake_complete
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket", AsyncMock(side_effect=lambda _s, c, _st: c)
    )
    monkeypatch.setattr("app.services.teamwork_sync.embed_query", fake_embed_query)
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", fake_upsert_ticket)

    first = await client.post("/api/import/teamwork/sync-now")
    second = await client.post("/api/import/teamwork/sync-now")

    assert first.status_code == 200
    assert first.json()["status"] == "partial"
    assert first.json()["cursor"] == "2026-05-21T10:10:00Z"
    assert second.status_code == 200
    assert second.json()["status"] == "ok"
    assert embed_calls == 1
    assert [call["cursor"] for call in completed] == [
        "2026-05-21T10:10:00Z",
        "2026-05-21T10:10:00Z",
    ]


@pytest.mark.asyncio
async def test_teamwork_sync_now_enqueues_aura_routing_for_open_unassigned_tickets(
    client, monkeypatch
):
    session = _FakeSession()
    enqueued = []
    gate_calls = []
    routing_status_updates = []

    async def fake_fetch_updated_tickets(updated_after: str):
        return [
            {
                "id": 333,
                "subject": "Unassigned live ticket",
                "preview": "Need routing",
                "status": "active",
                "updatedAt": "2026-05-21T10:07:00Z",
                "createdAt": "2026-05-21T10:05:00Z",
                "assignedTo": {},
                "company": {"name": "Acme"},
                "threads": [{"id": 1, "type": "message", "body": "Need routing"}],
            },
        ]

    async def fake_gate_and_persist_ticket(_session, ticket, **kwargs):
        gate_calls.append(
            {
                "ticket_id": str(ticket["id"]),
                "require_assignee": kwargs.get("require_assignee"),
                "require_closed": kwargs.get("require_closed"),
            }
        )
        return await _async_value(None)

    async def fake_set_ticket_aura_routing_status(_session, **kwargs):
        routing_status_updates.append(kwargs)
        await asyncio.sleep(0)

    _patch_sync_now_infra(monkeypatch, session)
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", _fake_none)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", _fake_none
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.gate_and_persist_ticket", fake_gate_and_persist_ticket
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(side_effect=AssertionError("Open tickets must not be summarized")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query",
        AsyncMock(side_effect=AssertionError("Open tickets must not be embedded")),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.set_ticket_aura_routing_status",
        fake_set_ticket_aura_routing_status,
    )
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}._enqueue_aura_routing_job", enqueued.append)

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 200
    assert resp.json()["needs_routing"] == 1
    assert enqueued == ["333"]
    assert routing_status_updates == [
        {"ticket_id": "333", "status": "queued"},
    ]
    assert gate_calls == [{"ticket_id": "333", "require_assignee": True, "require_closed": True}]


@pytest.mark.asyncio
async def test_teamwork_sync_now_reuses_existing_processing_when_request_unchanged(
    client, monkeypatch
):
    session = _FakeSession()
    upsert_calls = []

    async def fake_fetch_updated_tickets(updated_after: str):
        return await _async_value(
            [
                {
                    "id": 444,
                    "subject": "Existing ticket",
                    "preview": "Latest Teamwork preview",
                    "status": "closed",
                    "updatedAt": "2026-05-21T10:08:00Z",
                    "createdAt": "2026-05-21T10:05:00Z",
                    "assignedTo": {
                        "email": "expert@example.com",
                        "firstName": "Example",
                        "lastName": "Expert",
                    },
                    "company": {"name": "Acme"},
                },
            ]
        )

    async def fake_get_ticket_processing_payload(_session, ticket_id):
        return await _async_value(
            {
                "request_content": "Existing ticket\n\nNeed help with login",
                "content": "Stored Gemini summary",
                "raw_content": "Existing ticket\n\nNeed help with login\n\nAgent reply",
                "gemini_embedding": [0.4, 0.5, 0.6],
                "ticket_type": "Question",
                "inbox_name": "Support",
            }
        )

    async def fake_upsert_ticket(_session, ticket, **kwargs):
        upsert_calls.append(ticket)
        return await _async_value(None)

    _patch_sync_now_infra(monkeypatch, session)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.ticket_exists", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_ticket_processing_payload",
        fake_get_ticket_processing_payload,
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_ticket_full",
        AsyncMock(
            side_effect=AssertionError(
                "Existing processed tickets should not fetch full ticket details"
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_ticket_threads",
        AsyncMock(
            side_effect=AssertionError("Existing processed tickets should not fetch threads")
        ),
    )
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", _fake_none
    )
    monkeypatch.setattr("app.services.teamwork_sync.gate_and_persist_ticket", _fake_none)
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(
            side_effect=AssertionError("Existing unchanged requests should not be summarized again")
        ),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query",
        AsyncMock(
            side_effect=AssertionError("Existing unchanged requests should not be embedded again")
        ),
    )

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 200
    assert upsert_calls[0]["request_content"] == "Existing ticket\n\nNeed help with login"
    assert upsert_calls[0]["content"] == "Stored Gemini summary"
    assert (
        upsert_calls[0]["raw_content"] == "Existing ticket\n\nNeed help with login\n\nAgent reply"
    )
    assert upsert_calls[0]["embedding"] == [0.4, 0.5, 0.6]
    assert upsert_calls[0]["ticket_type"] == "Question"
    assert upsert_calls[0]["inbox_name"] == "Support"


@pytest.mark.asyncio
async def test_teamwork_sync_now_scrubs_stale_embedding_from_open_ticket(client, monkeypatch):
    """A previously embedded ticket that no longer qualifies (open) loses its
    embedding on the next sync touch, without re-running summarize/embed."""
    session = _FakeSession()
    upsert_calls = []

    async def fake_fetch_updated_tickets(updated_after: str):
        return await _async_value(
            [
                {
                    "id": 445,
                    "subject": "Reopened ticket",
                    "preview": "Latest Teamwork preview",
                    "status": "active",
                    "updatedAt": "2026-05-21T10:08:00Z",
                    "createdAt": "2026-05-21T10:05:00Z",
                    "assignedTo": {
                        "email": "expert@example.com",
                        "firstName": "Example",
                        "lastName": "Expert",
                    },
                    "company": {"name": "Acme"},
                },
            ]
        )

    async def fake_get_ticket_processing_payload(_session, ticket_id):
        return await _async_value(
            {
                "request_content": "Reopened ticket\n\nNeed help with login",
                "content": "Stored Gemini summary",
                "raw_content": "Reopened ticket\n\nNeed help with login\n\nAgent reply",
                "gemini_embedding": [0.4, 0.5, 0.6],
                "ticket_type": "Question",
                "inbox_name": "Support",
            }
        )

    async def fake_upsert_ticket(_session, ticket, **kwargs):
        upsert_calls.append(ticket)
        return await _async_value(None)

    _patch_sync_now_infra(monkeypatch, session)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.ticket_exists", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_ticket_processing_payload",
        fake_get_ticket_processing_payload,
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.tw.fetch_updated_tickets", fake_fetch_updated_tickets
    )
    monkeypatch.setattr("app.services.teamwork_sync.queries.upsert_ticket", fake_upsert_ticket)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.upsert_teamwork_assigned_to", _fake_none
    )
    monkeypatch.setattr("app.services.teamwork_sync.gate_and_persist_ticket", _fake_none)
    monkeypatch.setattr(
        "app.services.teamwork_sync.summarize_ticket",
        AsyncMock(
            side_effect=AssertionError("Existing unchanged requests should not be summarized again")
        ),
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.embed_query",
        AsyncMock(side_effect=AssertionError("Open tickets must not be embedded")),
    )
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}._enqueue_aura_routing_job", lambda _: None)

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 200
    assert upsert_calls[0]["content"] == "Stored Gemini summary"
    assert upsert_calls[0]["embedding"] is None


@pytest.mark.asyncio
async def test_teamwork_auto_sync_settings_endpoints_default_disabled_and_persist(
    client, monkeypatch
):
    session = _FakeSession()
    saved = []

    async def fake_get(_session):
        return {"enabled": False, "interval_seconds": 60}

    async def fake_set(_session, enabled: bool, interval_seconds: int):
        saved.append({"enabled": enabled, "interval_seconds": interval_seconds})
        return {"enabled": enabled, "interval_seconds": interval_seconds}

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.get_teamwork_auto_sync_settings", fake_get
    )
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.set_teamwork_auto_sync_settings", fake_set
    )

    get_resp = await client.get("/api/import/teamwork/auto-sync")
    put_resp = await client.put(
        "/api/import/teamwork/auto-sync", json={"enabled": True, "interval_seconds": 300}
    )

    assert get_resp.status_code == 200
    assert get_resp.json() == {"enabled": False, "interval_seconds": 60}
    assert put_resp.status_code == 200
    assert put_resp.json() == {"enabled": True, "interval_seconds": 300}
    assert saved == [{"enabled": True, "interval_seconds": 300}]


@pytest.mark.asyncio
async def test_post_aura_suggestion_endpoint_posts_private_note_for_latest_suggestion(
    client, monkeypatch
):
    session = _FakeSession()
    note_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "latest_aura_suggestion_email": "expert@example.com",
            "latest_aura_suggestion_name": "Example Expert",
        }

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr("app.api.routes.routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr("app.api.routes.routing.tw.post_private_note", fake_post_private_note)

    resp = await client.post("/api/import/tickets/123/post-aura-suggestion")

    assert resp.status_code == 200
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Korca Aura suggests Example Expert (expert@example.com) for this ticket.",
            "mention_email": "expert@example.com",
            "mention_name": "Example Expert",
        }
    ]


@pytest.mark.asyncio
async def test_assign_aura_suggestion_endpoint_assigns_latest_suggestion(client, monkeypatch):
    session = _FakeSession()
    assign_calls = []
    note_calls = []
    assignment_updates = []
    finalized = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {
            "id": ticket_id,
            "latest_aura_suggestion_email": "expert@example.com",
            "latest_aura_suggestion_name": "Example Expert",
        }

    async def fake_assign_ticket_to_expert(**kwargs):
        assign_calls.append(kwargs)
        return {"ok": True}

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_upsert_teamwork_assigned_to(_session, **kwargs):
        assignment_updates.append(kwargs)
        return "assigned"

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        finalized.append(ticket_id)
        return {"outcome": "correct"}

    monkeypatch.setattr("app.api.routes.routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.api.routes.routing.tw.assign_ticket_to_expert", fake_assign_ticket_to_expert
    )
    monkeypatch.setattr("app.api.routes.routing.tw.post_private_note", fake_post_private_note)
    # _mirror_korca_assignment lives in aura_routing service — patch its DB context and queries
    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.upsert_teamwork_assigned_to",
        fake_upsert_teamwork_assigned_to,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )

    resp = await client.post("/api/import/tickets/123/assign-aura-suggestion")

    assert resp.status_code == 200
    assert assign_calls == [{"ticket_id": 123, "expert_email": "expert@example.com"}]
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Ticket was assigned to Example Expert.",
            "mention_email": "expert@example.com",
            "mention_name": "Example Expert",
        }
    ]
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
async def test_post_staging_expert_endpoint_posts_private_note(client, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "staging@example.com")
    monkeypatch.setattr(_settings, "teamwork_staging_expert_name", "Staging Expert")

    session = _FakeSession()
    note_calls = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {"id": ticket_id}

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr("app.api.routes.routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr("app.api.routes.routing.tw.post_private_note", fake_post_private_note)

    resp = await client.post("/api/import/tickets/123/post-staging-expert")

    assert resp.status_code == 200
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Korca Aura suggests Staging Expert (staging@example.com) for this ticket.",
            "mention_email": "staging@example.com",
            "mention_name": "Staging Expert",
        }
    ]


@pytest.mark.asyncio
async def test_post_staging_expert_returns_503_when_not_configured(client, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "")

    resp = await client.post("/api/import/tickets/123/post-staging-expert")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_assign_staging_expert_endpoint_assigns_configured_expert(client, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "staging@example.com")
    monkeypatch.setattr(_settings, "teamwork_staging_expert_name", "Staging Expert")

    session = _FakeSession()
    assign_calls = []
    note_calls = []
    assignment_updates = []
    finalized = []

    async def fake_get_ticket_full(_session, ticket_id: str):
        return {"id": ticket_id}

    async def fake_assign_ticket_to_expert(**kwargs):
        assign_calls.append(kwargs)
        return {"ok": True}

    async def fake_post_private_note(**kwargs):
        note_calls.append(kwargs)
        return {"ok": True}

    async def fake_upsert_teamwork_assigned_to(_session, **kwargs):
        assignment_updates.append(kwargs)
        return "assigned"

    async def fake_finalize_latest_routing_event_for_ticket(_session, ticket_id: str):
        finalized.append(ticket_id)
        return {"outcome": "wrong"}

    monkeypatch.setattr("app.api.routes.routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.api.routes.routing.queries.get_ticket_full", fake_get_ticket_full)
    monkeypatch.setattr(
        "app.api.routes.routing.tw.assign_ticket_to_expert", fake_assign_ticket_to_expert
    )
    monkeypatch.setattr("app.api.routes.routing.tw.post_private_note", fake_post_private_note)
    # _mirror_korca_assignment lives in aura_routing service — patch its DB context and queries
    monkeypatch.setattr("app.services.aura_routing.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        "app.services.aura_routing.queries.upsert_teamwork_assigned_to",
        fake_upsert_teamwork_assigned_to,
    )
    monkeypatch.setattr(
        "app.services.aura_routing.queries.finalize_latest_routing_event_for_ticket",
        fake_finalize_latest_routing_event_for_ticket,
    )

    resp = await client.post("/api/import/tickets/123/assign-staging-expert")

    assert resp.status_code == 200
    assert assign_calls == [{"ticket_id": 123, "expert_email": "staging@example.com"}]
    assert note_calls == [
        {
            "ticket_id": 123,
            "message": "Ticket was assigned to Staging Expert.",
            "mention_email": "staging@example.com",
            "mention_name": "Staging Expert",
        }
    ]
    assert assignment_updates == [
        {
            "ticket_id": "123",
            "agent_email": "staging@example.com",
            "agent_name": "Staging Expert",
            "final": False,
            "source": "korca_assignment",
        }
    ]
    assert finalized == ["123"]


@pytest.mark.asyncio
async def test_assign_staging_expert_returns_503_when_not_configured(client, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "teamwork_staging_expert_email", "")

    resp = await client.post("/api/import/tickets/123/assign-staging-expert")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_teamwork_sync_now_refuses_when_redis_lock_already_held(client, monkeypatch):
    """Redis lock already held by another process → 409."""
    session = _FakeSession()
    monkeypatch.setattr("app.services.teamwork_sync.Redis", _FakeRedisLocked)
    monkeypatch.setattr("app.services.teamwork_sync.db_context", lambda: _FakeDbContext(session))

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_teamwork_import_enqueues_background_job(client, monkeypatch):
    from app.services.teamwork_import_status import TEAMWORK_IMPORT_LOCK

    queued_tokens = []
    _FakeRedis.instances.clear()

    def fake_enqueue(lock_token: str):
        queued_tokens.append(lock_token)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.Redis", _FakeRedis)
    monkeypatch.setattr("app.services.teamwork_import_status.Redis", _FakeRedis)
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}._enqueue_full_teamwork_import", fake_enqueue)

    resp = await client.post("/api/import/teamwork")

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    redis = _FakeRedis.instances[0]
    assert queued_tokens == [redis.values[TEAMWORK_IMPORT_LOCK]]


@pytest.mark.asyncio
async def test_start_teamwork_import_returns_already_running_when_lock_held(client, monkeypatch):
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.Redis", _FakeRedisLocked)

    resp = await client.post("/api/import/teamwork")

    assert resp.status_code == 200
    assert resp.json() == {"status": "already_running"}


@pytest.mark.asyncio
async def test_teamwork_import_progress_idle_event_closes_when_no_import_exists(
    client, monkeypatch
):
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.Redis", _FakeRedis)

    async with client.stream("GET", "/api/import/teamwork/progress") as resp:
        assert resp.status_code == 200
        data_lines = [
            line[len("data: ") :] async for line in resp.aiter_lines() if line.startswith("data: ")
        ]

    assert len(data_lines) == 1
    parsed = json.loads(data_lines[0])
    assert parsed["status"] == "idle"


@pytest.mark.asyncio
async def test_teamwork_import_progress_events_stop_after_max_running_ticks(monkeypatch):
    from app.api.routes import teamwork_import
    from app.services.teamwork_import_status import TeamworkImportProgress

    async def fake_effective_progress(_redis):
        return await _async_value(
            (TeamworkImportProgress(status="running", message="Still importing"), True)
        )

    async def fake_sleep(_delay):
        await _async_value(None)

    monkeypatch.setattr(
        teamwork_import,
        "get_effective_import_progress",
        fake_effective_progress,
    )
    monkeypatch.setattr(teamwork_import.asyncio, "sleep", fake_sleep)

    events = []
    async for event in teamwork_import._teamwork_import_progress_events(max_events=2):
        events.append(json.loads(event["data"]))

    assert [event["status"] for event in events] == ["running", "running"]


@pytest.mark.asyncio
async def test_clear_teamwork_tickets_refuses_during_full_import(client, monkeypatch):
    async def fake_running():
        return await _async_value(True)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.is_full_import_running", fake_running)

    resp = await client.delete("/api/import/teamwork/tickets")

    assert resp.status_code == 409
    assert "import running" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sync_now_refuses_during_full_import(client, monkeypatch):
    async def fake_running():
        return await _async_value(True)

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.is_full_import_running", fake_running)

    resp = await client.post("/api/import/teamwork/sync-now")

    assert resp.status_code == 409
    assert "import running" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_teamwork_status_reflects_redis_lock(client, monkeypatch):
    """import_running in status response reflects the Redis lock, not a process-local bool."""
    session = _FakeSession()

    async def fake_count(_session, source_system):
        return await _async_value(42)

    class _FakeResultWithSingle(_FakeResult):
        async def single(self):
            return await _async_value({"last_imported_at": "2026-05-25T10:00:00Z"})

    async def fake_run(query, **params):
        await _async_value(None)
        session.calls.append((query, params))
        return _FakeResultWithSingle()

    session.run = fake_run

    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.queries.count_tickets", fake_count)
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))

    # Lock not held — import_running should be False
    monkeypatch.setattr("app.services.teamwork_import_status.Redis", _FakeRedis)
    resp = await client.get("/api/import/teamwork/status")
    assert resp.status_code == 200
    assert resp.json()["import_running"] is False

    # Lock held — import_running should be True
    monkeypatch.setattr("app.services.teamwork_import_status.Redis", _FakeRedisLocked)
    resp = await client.get("/api/import/teamwork/status")
    assert resp.status_code == 200
    assert resp.json()["import_running"] is True


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation)


def test_teamwork_route_handlers_have_typed_response_models():
    from app.api.routes import teamwork_import

    assert (
        _return_annotation_name(teamwork_import.teamwork_filter_options)
        == "TeamworkFilterOptionsResponse"
    )
    assert _return_annotation_name(teamwork_import.list_teamwork_tickets) == "list[TicketResponse]"
    assert (
        _return_annotation_name(teamwork_import.get_teamwork_auto_sync)
        == "TeamworkAutoSyncResponse"
    )
    assert (
        _return_annotation_name(teamwork_import.set_teamwork_auto_sync)
        == "TeamworkAutoSyncResponse"
    )
    assert (
        _return_annotation_name(teamwork_import.bootstrap_teamwork_sync)
        == "TeamworkSyncStateResponse"
    )


@pytest.mark.asyncio
async def test_teamwork_filter_options_returns_typed_model(client, monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.get_cached_data", AsyncMock(return_value=None))
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.set_cached_data", AsyncMock(return_value=None))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.get_teamwork_filter_options",
        AsyncMock(return_value={"clients": ["Acme"], "agents": ["Alice"], "inboxes": ["Support"]}),
    )

    resp = await client.get("/api/import/teamwork/filters")

    assert resp.status_code == 200
    assert resp.json() == {"clients": ["Acme"], "agents": ["Alice"], "inboxes": ["Support"]}


@pytest.mark.asyncio
async def test_list_teamwork_tickets_returns_ticket_response_models(client, monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(f"{TEAMWORK_IMPORT_ROUTE}.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr(
        f"{TEAMWORK_IMPORT_ROUTE}.queries.list_tickets",
        AsyncMock(
            return_value=[{"id": 4093106, "subject": "Login broken", "source_system": "teamwork"}]
        ),
    )

    resp = await client.get("/api/import/teamwork/tickets")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # Teamwork stores numeric ticket IDs — they must coerce to string, not 500.
    assert body[0]["id"] == "4093106"
    assert body[0]["subject"] == "Login broken"
