"""Ticket CRUD, listing, staging, reassignment, and gatekeeper routes."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db import queries
from app.db.connection import db_context
from app.services.gatekeeper import gate_and_persist_ticket
from app.services.teamwork_sync import _is_closed_status

logger = structlog.get_logger()
router = APIRouter()


class ReassignRequest(BaseModel):
    expert_email: str
    expert_name: str = ""


class ReassignResponse(BaseModel):
    ticket_id: str
    assigned_to: str
    auto_promoted: bool


class BulkDeleteRequest(BaseModel):
    ticket_ids: list[str]


class BulkDeleteResponse(BaseModel):
    deleted: int


class StagedTicketsResponse(BaseModel):
    tickets: list[dict[str, Any]]
    total: int


class PromoteTicketResponse(BaseModel):
    ticket_id: str
    ingest_status: str


class RouteSuggestionResponse(BaseModel):
    # Parsed from stored JSON, so tolerate partial/legacy shapes and keep extras.
    model_config = ConfigDict(extra="allow")

    user_id: str | None = None
    name: str | None = None
    email: str | None = None
    tickets_matched: int | None = None
    avg_score: float | None = None
    topics: list[str] = Field(default_factory=list)
    sample_subjects: list[str] = Field(default_factory=list)
    client_tickets: int | None = None
    match_reason: str | None = None


class TicketResponse(BaseModel):
    """Compatible with the frontend `Ticket` type, but more tolerant. The list
    and detail queries each populate a subset; only `id` is guaranteed, so the
    rest stay optional/nullable to avoid rejecting otherwise-valid rows.
    `gemini_embedding` and any other internal field is dropped (default
    `extra="ignore"`)."""

    id: str
    subject: str | None = None
    preview: str | None = None
    status: str | None = None
    source: str | None = None
    source_system: str | None = None
    ticket_type: str | None = None
    inbox_name: str | None = None
    created_at: str | None = None
    resolved_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    agent_name: str | None = None
    agent_email: str | None = None
    assigned_to_name: str | None = None
    assigned_to_email: str | None = None
    client_name: str | None = None
    client_domain: str | None = None
    client_display_name: str | None = None
    content: str | None = None
    request_content: str | None = None
    request_preview: str | None = None
    raw_content: str | None = None
    routed_to_name: str | None = None
    routed_to_email: str | None = None
    is_mismatch: bool | None = None
    latest_routing_event_id: str | None = None
    latest_routing_event_outcome: str | None = None
    latest_aura_suggestion_email: str | None = None
    latest_aura_suggestion_name: str | None = None
    routing_status: str | None = None
    aura_routing_error: str | None = None
    teamwork_action_error: str | None = None
    routing_suggestions: list[RouteSuggestionResponse] | None = None
    routed_at: str | None = None
    confirmed_expert_email: str | None = None
    confirmed_expert_name: str | None = None
    confirmed_at: str | None = None
    is_override: bool | None = None
    aura_suggestion_email: str | None = None
    aura_suggestion_confidence: str | None = None
    ingest_status: str | None = None
    staged_reasons: list[str] | None = None
    gatekeeper_notes: str | None = None
    gated_at: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> Any:
        # Teamwork ticket IDs are stored as integers; the API/UI treat them as
        # strings, so coerce before validation to avoid rejecting real rows.
        return str(value) if isinstance(value, int) else value


def _ticket_response(data: dict[str, Any]) -> TicketResponse:
    return TicketResponse.model_validate(data)


def _ticket_responses(rows: list[dict[str, Any]]) -> list[TicketResponse]:
    return [_ticket_response(row) for row in rows]


@router.get("/tickets")
async def list_all_tickets(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> list[TicketResponse]:
    """All tickets across all sources — used by dashboard."""
    async with db_context() as session:
        rows = await queries.list_tickets(session, offset=offset, limit=limit)
    return _ticket_responses(rows)


@router.get("/tickets/{ticket_id}", responses={404: {"description": "Ticket not found"}})
async def get_ticket(ticket_id: str) -> TicketResponse:
    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _ticket_response(ticket)


@router.post(
    "/tickets/{ticket_id}/reassign",
    responses={
        422: {"description": "expert_email is required"},
        404: {"description": "Ticket not found"},
    },
)
async def reassign_ticket_resolver(ticket_id: str, body: ReassignRequest) -> ReassignResponse:
    """Replace the canonical assignment with a corrected expert.

    If the ticket is staged, run gatekeeper after reassigning — an assignee
    was the likely missing piece, so auto-promote if it now passes.
    """
    if not body.expert_email:
        raise HTTPException(status_code=422, detail="expert_email is required")
    async with db_context() as session:
        current_ticket = await queries.get_ticket_full(session, ticket_id)
        if not current_ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        protect_assignment = current_ticket.get("ingest_status") == "promoted" or _is_closed_status(
            current_ticket.get("status")
        )
        ok = await queries.reassign_assigned_to(
            session,
            ticket_id,
            body.expert_email,
            body.expert_name,
            protected=protect_assignment,
            final=protect_assignment,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Ticket not found")
        await queries.finalize_latest_routing_event_for_ticket(session, ticket_id)
        ticket = await queries.get_ticket_full(session, ticket_id)
        auto_promoted = False
        if ticket and ticket.get("ingest_status") == "staged":
            gate_result = await gate_and_persist_ticket(
                session,
                ticket,
                require_assignee=True,
                require_closed=True,
            )
            auto_promoted = gate_result.passed
            if auto_promoted:
                logger.info("Ticket auto-promoted on reassign", ticket_id=ticket_id)
    return ReassignResponse(
        ticket_id=ticket_id,
        assigned_to=body.expert_email,
        auto_promoted=auto_promoted,
    )


@router.delete(
    "/tickets/{ticket_id}", status_code=204, responses={404: {"description": "Ticket not found"}}
)
async def delete_ticket(ticket_id: str) -> None:
    """Remove a ticket from the knowledge graph only. Does not blocklist.

    GUARDRAIL: This endpoint MUST NOT call Teamwork APIs.
    Deletion is graph-local. The source system record is never touched.
    """
    async with db_context() as session:
        deleted = await queries.delete_ticket(session, ticket_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.post(
    "/tickets/{ticket_id}/spam",
    status_code=204,
    responses={404: {"description": "Ticket not found"}},
)
async def spam_ticket(ticket_id: str) -> None:
    """Remove a ticket and blocklist its ID so it is never re-imported.

    GUARDRAIL: This endpoint MUST NOT call Teamwork APIs.
    Deletion is graph-local. The source system record is never touched.
    """
    async with db_context() as session:
        deleted = await queries.spam_ticket(session, ticket_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ticket not found")


@router.post("/tickets/bulk-delete")
async def bulk_delete_tickets(body: BulkDeleteRequest) -> BulkDeleteResponse:
    """Delete multiple tickets and blocklist them so they are never re-imported.

    GUARDRAIL: This endpoint MUST NOT call Teamwork APIs.
    Deletion is graph-local. The source system records are never touched.
    """
    if not body.ticket_ids:
        return BulkDeleteResponse(deleted=0)
    async with db_context() as session:
        deleted = await queries.bulk_delete_tickets(session, body.ticket_ids)
    return BulkDeleteResponse(deleted=deleted)


@router.get("/staged")
async def list_staged(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> StagedTicketsResponse:
    """Return tickets currently in the staged queue with counts."""
    async with db_context() as session:
        tickets = await queries.list_staged_tickets(session, offset=offset, limit=limit)
        total = await queries.count_staged_tickets(session)
    return StagedTicketsResponse(tickets=tickets, total=total)


@router.post(
    "/tickets/{ticket_id}/promote",
    responses={
        404: {"description": "Ticket not found"},
        409: {"description": "Ticket must be closed and have an assigned expert before promotion"},
    },
)
async def promote_ticket(ticket_id: str) -> PromoteTicketResponse:
    """Manually promote a staged ticket after it has closed with an assignment."""
    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        if not _is_closed_status(ticket.get("status")):
            raise HTTPException(status_code=409, detail="Ticket must be closed before promotion")
        if not (ticket.get("assigned_to_email") or ticket.get("agent_email")):
            raise HTTPException(
                status_code=409, detail="Ticket must have an assigned expert before promotion"
            )
        await queries.set_ticket_ingest_status(
            session,
            ticket_id=ticket_id,
            status="promoted",
            reasons=None,
            notes="Manually promoted by reviewer",
        )
    logger.info("Ticket manually promoted", ticket_id=ticket_id)
    return PromoteTicketResponse(ticket_id=ticket_id, ingest_status="promoted")
