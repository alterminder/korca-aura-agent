from contextlib import asynccontextmanager
from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes import tickets


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.tickets.", "")


def _fake_db_context(session=None):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


def test_ticket_route_handlers_have_typed_response_models():
    assert _return_annotation_name(tickets.list_all_tickets) == "list[TicketResponse]"
    assert _return_annotation_name(tickets.get_ticket) == "TicketResponse"


@pytest.mark.asyncio
async def test_list_all_tickets_returns_response_models(monkeypatch):
    monkeypatch.setattr(tickets, "db_context", _fake_db_context())
    monkeypatch.setattr(
        tickets.queries,
        "list_tickets",
        AsyncMock(
            return_value=[
                {
                    "id": "tkt_1",
                    "subject": "DNS not resolving",
                    "preview": "Our records...",
                    "status": "open",
                    "source": "teamwork",
                    "tags": ["dns"],
                    "created_at": "2026-06-01T10:00:00Z",
                    "client_display_name": "Acme",
                }
            ]
        ),
    )

    result = await tickets.list_all_tickets(offset=0, limit=20)

    assert [type(item).__name__ for item in result] == ["TicketResponse"]
    assert result[0].subject == "DNS not resolving"
    assert result[0].tags == ["dns"]


@pytest.mark.asyncio
async def test_list_all_tickets_tolerates_sparse_rows(monkeypatch):
    monkeypatch.setattr(tickets, "db_context", _fake_db_context())
    monkeypatch.setattr(
        tickets.queries,
        "list_tickets",
        AsyncMock(return_value=[{"id": "tkt_min"}]),
    )

    result = await tickets.list_all_tickets(offset=0, limit=20)

    assert result[0].id == "tkt_min"
    assert result[0].subject is None
    assert result[0].tags == []


@pytest.mark.asyncio
async def test_get_ticket_drops_internal_fields_and_parses_suggestions(monkeypatch):
    monkeypatch.setattr(tickets, "db_context", _fake_db_context())
    monkeypatch.setattr(
        tickets.queries,
        "get_ticket_full",
        AsyncMock(
            return_value={
                "id": "tkt_1",
                "subject": "DNS not resolving",
                "status": "open",
                "source": "teamwork",
                "raw_content": "raw email body",
                "gemini_embedding": [0.1, 0.2, 0.3],
                "routing_suggestions": [
                    {"user_id": "u1", "name": "Alice", "email": "a@x.com", "avg_score": 0.91}
                ],
            }
        ),
    )

    result = await tickets.get_ticket("tkt_1")

    assert type(result).__name__ == "TicketResponse"
    # internal embedding must not leak into the response
    assert "gemini_embedding" not in result.model_dump()
    assert result.raw_content == "raw email body"
    assert result.routing_suggestions is not None
    assert result.routing_suggestions[0].name == "Alice"
    assert result.routing_suggestions[0].avg_score == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_get_ticket_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(tickets, "db_context", _fake_db_context())
    monkeypatch.setattr(tickets.queries, "get_ticket_full", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await tickets.get_ticket("nope")

    assert exc.value.status_code == 404


def test_ticket_response_coerces_numeric_id():
    # Teamwork stores numeric ticket IDs; the model must coerce, not reject.
    assert tickets.TicketResponse.model_validate({"id": 4093106}).id == "4093106"
    assert tickets.TicketResponse.model_validate({"id": "tkt_1"}).id == "tkt_1"
