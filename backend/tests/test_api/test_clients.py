from contextlib import asynccontextmanager
from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes import clients


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.clients.", "")


def _fake_db_context(session=None):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


def test_client_route_handlers_have_typed_response_models():
    assert _return_annotation_name(clients.list_clients) == "list[ClientResponse]"
    assert _return_annotation_name(clients.get_client) == "ClientDetailResponse"


@pytest.mark.asyncio
async def test_list_clients_returns_response_models(monkeypatch):
    monkeypatch.setattr(clients, "db_context", _fake_db_context())
    monkeypatch.setattr(
        clients.queries,
        "list_clients",
        AsyncMock(
            return_value=[
                {
                    "domain": "acme.com",
                    "name": "Acme",
                    "display_name": "Acme",
                    "ticket_count": 7,
                    "parent_domain": None,
                    "parent_name": None,
                }
            ]
        ),
    )

    result = await clients.list_clients(offset=0, limit=50, search=None)

    assert [type(item).__name__ for item in result] == ["ClientResponse"]
    assert result[0].domain == "acme.com"
    assert result[0].ticket_count == 7


@pytest.mark.asyncio
async def test_list_clients_tolerates_nameless_sparse_rows(monkeypatch):
    monkeypatch.setattr(clients, "db_context", _fake_db_context())
    monkeypatch.setattr(
        clients.queries,
        "list_clients",
        AsyncMock(return_value=[{"domain": "noname.io", "display_name": "Noname"}]),
    )

    result = await clients.list_clients(offset=0, limit=50, search=None)

    assert result[0].domain == "noname.io"
    assert result[0].name is None
    assert result[0].ticket_count == 0


@pytest.mark.asyncio
async def test_get_client_returns_detail_with_agents_and_tickets(monkeypatch):
    monkeypatch.setattr(clients, "db_context", _fake_db_context())
    monkeypatch.setattr(
        clients.queries,
        "get_client",
        AsyncMock(
            return_value={
                "domain": "acme.com",
                "name": "Acme",
                "display_name": "Acme",
                "ticket_count": 2,
                "agents": ["Alice", "Bob"],
                "tickets": [
                    {
                        "id": "tkt_1",
                        "subject": "DNS",
                        "status": "open",
                        "created_at": "2026-06-01T10:00:00Z",
                        "source_system": "teamwork",
                    }
                ],
                "parent_domain": None,
                "parent_name": None,
            }
        ),
    )

    result = await clients.get_client("acme.com")

    assert type(result).__name__ == "ClientDetailResponse"
    assert result.agents == ["Alice", "Bob"]
    assert type(result.tickets[0]).__name__ == "ClientTicketItem"
    assert result.tickets[0].subject == "DNS"


@pytest.mark.asyncio
async def test_get_client_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(clients, "db_context", _fake_db_context())
    monkeypatch.setattr(clients.queries, "get_client", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await clients.get_client("nope.com")

    assert exc.value.status_code == 404


def test_client_ticket_item_coerces_numeric_id():
    # Embedded ticket summaries carry Teamwork's numeric IDs — coerce, don't reject.
    assert clients.ClientTicketItem.model_validate({"id": 4093106}).id == "4093106"
