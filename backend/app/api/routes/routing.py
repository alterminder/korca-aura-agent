"""Ticket routing action routes — Aura-agent reroute and post/assign helpers."""

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.db import queries
from app.db.connection import db_context
from app.limiter import limiter
from app.services import teamwork as tw
from app.services.aura_routing import (
    _assignment_note,
    _aura_suggestion_note,
    _mirror_korca_assignment,
    _teamwork_ticket_id,
)
from app.services.aura_routing import (
    route_ticket_with_aura as _route_ticket_with_aura,
)
from app.services.gatekeeper import gate_and_persist_ticket

logger = structlog.get_logger()
router = APIRouter()


class ConfirmRoutingRequest(BaseModel):
    expert_email: str
    expert_name: str = ""
    is_override: bool = False


class ConfirmRoutingResponse(BaseModel):
    ticket_id: str
    confirmed_expert_email: str
    is_override: bool
    auto_promoted: bool


class TeamworkActionResponse(BaseModel):
    ticket_id: str
    action: str
    teamwork: dict[str, Any]


class TeamworkAssignResponse(BaseModel):
    ticket_id: str
    action: str
    teamwork: dict[str, Any]
    graph_sync: dict[str, Any]


def _teamwork_http_detail(exc: httpx.HTTPStatusError) -> str:
    body = exc.response.text[:500]
    return f"Teamwork API returned {exc.response.status_code}: {body}"


def _latest_aura_suggestion(ticket: dict) -> tuple[str | None, str | None]:
    email = ticket.get("latest_aura_suggestion_email") or ticket.get("aura_suggestion_email")
    name = ticket.get("latest_aura_suggestion_name")
    if email and not name and (ticket.get("routed_to_email") or "").lower() == email.lower():
        name = ticket.get("routed_to_name")
    if email and not name:
        for suggestion in ticket.get("routing_suggestions") or []:
            if (suggestion.get("email") or "").lower() == email.lower():
                name = suggestion.get("name")
                break
    return email, name


class RouteTicketAuraResponse(BaseModel):
    ticket_id: str
    expert_email: str | None = None
    expert_name: str | None = None
    routing_event: dict[str, Any] | None = None


@router.post("/tickets/{ticket_id}/route-aura")
@limiter.limit("10/minute")
async def route_ticket_with_aura(request: Request, ticket_id: str) -> RouteTicketAuraResponse:
    """Manually reroute a ticket and store the Aura suggestion only."""
    result = await _route_ticket_with_aura(ticket_id, apply_teamwork_actions=False)
    return RouteTicketAuraResponse.model_validate(result)


@router.post(
    "/tickets/{ticket_id}/confirm",
    responses={
        422: {"description": "expert_email is required"},
        404: {"description": "Ticket not found"},
    },
)
async def confirm_ticket_routing(
    ticket_id: str, body: ConfirmRoutingRequest
) -> ConfirmRoutingResponse:
    """Confirm or override the routing suggestion for a ticket.

    If the ticket is still staged, confirming routing auto-promotes it —
    a human confirming an expert is the strongest possible quality signal.
    """
    expert_email = body.expert_email.strip()
    expert_name = body.expert_name.strip()
    is_override = body.is_override
    if not expert_email:
        raise HTTPException(status_code=422, detail="expert_email is required")
    async with db_context() as session:
        ok = await queries.confirm_routing(
            session, ticket_id, expert_email, expert_name, is_override
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Ticket not found")
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
                logger.info(
                    "Ticket auto-promoted on confirm (passed gatekeeper)", ticket_id=ticket_id
                )
            else:
                logger.info(
                    "Ticket remains staged after confirm (gatekeeper failed)",
                    ticket_id=ticket_id,
                    reasons=gate_result.reasons,
                )
    return ConfirmRoutingResponse(
        ticket_id=ticket_id,
        confirmed_expert_email=expert_email,
        is_override=is_override,
        auto_promoted=auto_promoted,
    )


@router.post(
    "/tickets/{ticket_id}/post-aura-suggestion",
    responses={
        404: {"description": "Ticket not found"},
        422: {"description": "Ticket has no Aura suggestion"},
        502: {"description": "Teamwork API error"},
    },
)
async def post_ticket_aura_suggestion(ticket_id: str) -> TeamworkActionResponse:
    """Post the latest Aura suggestion as a private Teamwork note."""
    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    expert_email, expert_name = _latest_aura_suggestion(ticket)
    if not expert_email:
        raise HTTPException(status_code=422, detail="Ticket has no Aura suggestion")

    try:
        result = await tw.post_private_note(
            ticket_id=_teamwork_ticket_id(ticket_id),
            message=_aura_suggestion_note(expert_name, expert_email),
            mention_email=expert_email,
            mention_name=expert_name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_teamwork_http_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TeamworkActionResponse(ticket_id=ticket_id, action="posted_comment", teamwork=result)


@router.post(
    "/tickets/{ticket_id}/assign-aura-suggestion",
    responses={
        404: {"description": "Ticket not found"},
        422: {"description": "Ticket has no Aura suggestion"},
        502: {"description": "Teamwork API error"},
    },
)
async def assign_ticket_aura_suggestion(ticket_id: str) -> TeamworkAssignResponse:
    """Assign the latest Aura suggested expert in Teamwork."""
    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    expert_email, expert_name = _latest_aura_suggestion(ticket)
    if not expert_email:
        raise HTTPException(status_code=422, detail="Ticket has no Aura suggestion")

    try:
        teamwork_ticket_id = _teamwork_ticket_id(ticket_id)
        result = await tw.assign_ticket_to_expert(
            ticket_id=teamwork_ticket_id,
            expert_email=expert_email,
        )
        await tw.post_private_note(
            ticket_id=teamwork_ticket_id,
            message=_assignment_note(expert_name, expert_email),
            mention_email=expert_email,
            mention_name=expert_name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_teamwork_http_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    graph_sync = await _mirror_korca_assignment(ticket_id, expert_email, expert_name)
    return TeamworkAssignResponse(
        ticket_id=ticket_id, action="assigned", teamwork=result, graph_sync=graph_sync
    )


@router.post(
    "/tickets/{ticket_id}/post-staging-expert",
    responses={
        503: {"description": "Staging expert not configured"},
        404: {"description": "Ticket not found"},
        502: {"description": "Teamwork API error"},
    },
)
async def post_ticket_staging_expert(ticket_id: str) -> TeamworkActionResponse:
    """Post the staging Teamwork expert as a private note."""
    expert_email = settings.teamwork_staging_expert_email
    expert_name = settings.teamwork_staging_expert_name
    if not expert_email:
        raise HTTPException(
            status_code=503, detail="TEAMWORK_STAGING_EXPERT_EMAIL is not configured"
        )

    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    try:
        result = await tw.post_private_note(
            ticket_id=_teamwork_ticket_id(ticket_id),
            message=_aura_suggestion_note(expert_name, expert_email),
            mention_email=expert_email,
            mention_name=expert_name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_teamwork_http_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TeamworkActionResponse(
        ticket_id=ticket_id, action="posted_staging_comment", teamwork=result
    )


@router.post(
    "/tickets/{ticket_id}/assign-staging-expert",
    responses={
        503: {"description": "Staging expert not configured"},
        404: {"description": "Ticket not found"},
        502: {"description": "Teamwork API error"},
    },
)
async def assign_ticket_staging_expert(ticket_id: str) -> TeamworkAssignResponse:
    """Assign the staging Teamwork expert."""
    expert_email = settings.teamwork_staging_expert_email
    expert_name = settings.teamwork_staging_expert_name
    if not expert_email:
        raise HTTPException(
            status_code=503, detail="TEAMWORK_STAGING_EXPERT_EMAIL is not configured"
        )

    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    try:
        teamwork_ticket_id = _teamwork_ticket_id(ticket_id)
        result = await tw.assign_ticket_to_expert(
            ticket_id=teamwork_ticket_id,
            expert_email=expert_email,
        )
        await tw.post_private_note(
            ticket_id=teamwork_ticket_id,
            message=_assignment_note(expert_name, expert_email),
            mention_email=expert_email,
            mention_name=expert_name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=_teamwork_http_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    graph_sync = await _mirror_korca_assignment(ticket_id, expert_email, expert_name)
    return TeamworkAssignResponse(
        ticket_id=ticket_id,
        action="assigned_staging_expert",
        teamwork=result,
        graph_sync=graph_sync,
    )
