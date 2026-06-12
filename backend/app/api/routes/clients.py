"""Client endpoints — companies derived from ticket imports."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import queries
from app.db.connection import db_context

logger = structlog.get_logger()
router = APIRouter()


class LinkParentRequest(BaseModel):
    parent_domain: str


class ClientLinkResponse(BaseModel):
    child: str
    parent: str


class ClientResponse(BaseModel):
    """Compatible with the frontend `Client` type (list shape), but more tolerant:
    `domain` is the node key and the only guaranteed field; `name` is nullable
    (that is why `display_name` exists), so the rest stay optional to avoid
    rejecting otherwise-valid rows."""

    domain: str
    name: str | None = None
    display_name: str | None = None
    ticket_count: int = 0
    parent_domain: str | None = None
    parent_name: str | None = None


class ClientTicketItem(BaseModel):
    # Embedded ticket summary from the detail query — tolerate partial shapes.
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    subject: str | None = None
    status: str | None = None
    created_at: str | None = None
    source_system: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> Any:
        # Teamwork ticket IDs are stored as integers; coerce to string.
        return str(value) if isinstance(value, int) else value


class ClientDetailResponse(ClientResponse):
    agents: list[str] = Field(default_factory=list)
    tickets: list[ClientTicketItem] = Field(default_factory=list)


def _client_response(data: dict[str, Any]) -> ClientResponse:
    return ClientResponse.model_validate(data)


def _client_responses(rows: list[dict[str, Any]]) -> list[ClientResponse]:
    return [_client_response(row) for row in rows]


@router.get("")
async def list_clients(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    search: str | None = Query(default=None, max_length=200),
) -> list[ClientResponse]:
    async with db_context() as session:
        rows = await queries.list_clients(session, offset=offset, limit=limit, search=search)
    return _client_responses(rows)


@router.post(
    "/{domain}/link",
    responses={
        400: {"description": "A client cannot be linked to itself"},
        404: {"description": "One or both clients not found"},
    },
)
async def link_client_parent(domain: str, body: LinkParentRequest) -> ClientLinkResponse:
    """Create a WORKS_FOR relationship: this client works for the parent client."""
    if domain == body.parent_domain:
        raise HTTPException(status_code=400, detail="A client cannot be linked to itself")
    async with db_context() as session:
        ok = await queries.link_client_parent(session, domain, body.parent_domain)
    if not ok:
        raise HTTPException(status_code=404, detail="One or both clients not found")
    logger.info("Client linked to parent", child=domain, parent=body.parent_domain)
    return ClientLinkResponse(child=domain, parent=body.parent_domain)


@router.delete("/{domain}/link", status_code=204)
async def unlink_client_parent(domain: str) -> None:
    """Remove the WORKS_FOR relationship from this client."""
    async with db_context() as session:
        await queries.unlink_client_parent(session, domain)


@router.get("/{domain:path}", responses={404: {"description": "Client not found"}})
async def get_client(domain: str) -> ClientDetailResponse:
    async with db_context() as session:
        client = await queries.get_client(session, domain)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return ClientDetailResponse.model_validate(client)
