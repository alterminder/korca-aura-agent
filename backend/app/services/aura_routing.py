"""Aura-hosted routing orchestration service.

Contains the core routing logic so both route handlers and the Celery worker
can import from here instead of creating a worker → routes import cycle.
"""

import re

import structlog

from app.config import settings
from app.db import queries
from app.db.connection import db_context
from app.exceptions import AuraAgentError, DomainValidationError, TicketNotFoundError
from app.services import teamwork as tw
from app.services.aura_agent import route_with_aura_agent
from app.services.aura_tracing import AuraTraceOutcome, trace_aura_route_call

logger = structlog.get_logger()

# Bounded email patterns — explicit length caps (RFC 5321: 64-char local part,
# 253-char domain) prevent catastrophic backtracking on crafted input (S5852).
# Both patterns use IGNORECASE so the character classes need only lowercase
# ranges — [a-zA-Z] with IGNORECASE duplicates coverage (S5869).
_RE_RECOMMENDED_EMAIL = re.compile(
    r"RECOMMENDED:\s*([a-z0-9_.+-]{1,64}@[a-z0-9.-]{1,253})",
    re.IGNORECASE,
)
_RE_EMAIL = re.compile(r"[a-z0-9_.+-]{1,64}@[a-z0-9.-]{1,253}", re.IGNORECASE)


def _parse_aura_expert_email(result: dict) -> str | None:
    """Extract the recommended expert email from an Aura agent response.

    Tries `output` field first, then falls back to `content` text blocks.
    Prefers explicit RECOMMENDED: <email> format; falls back to first email found.
    """
    output_text = result.get("output", "")
    if not output_text:
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                output_text = block.get("text", "")
                break
    recommended = _RE_RECOMMENDED_EMAIL.search(output_text)
    email_match = recommended or _RE_EMAIL.search(output_text)
    return email_match.group(1 if recommended else 0).lower() if email_match else None


_SET_TEAMWORK_ACTION_ERROR = """
MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
SET t.teamwork_action_error = $err
"""


def _teamwork_ticket_id(ticket_id: str) -> int:
    try:
        return int(ticket_id)
    except ValueError as exc:
        raise DomainValidationError("Teamwork ticket ID must be numeric") from exc


def _aura_suggestion_note(expert_name: str | None, expert_email: str) -> str:
    display = (expert_name or "").strip()
    if display:
        return f"Korca Aura suggests {display} ({expert_email}) for this ticket."
    return f"Korca Aura suggests {expert_email} for this ticket."


def _assignment_note(expert_name: str | None, expert_email: str) -> str:
    display = (expert_name or "").strip() or expert_email
    return f"Ticket was assigned to {display}."


def _fallback_teamwork_expert_name(expert_email: str) -> str | None:
    staging_email = settings.teamwork_staging_expert_email
    if staging_email and expert_email.lower() == staging_email.lower():
        return settings.teamwork_staging_expert_name or None
    return None


async def _mirror_korca_assignment(
    ticket_id: str, expert_email: str, expert_name: str | None
) -> dict:
    async with db_context() as session:
        assignment_result = await queries.upsert_teamwork_assigned_to(
            session,
            ticket_id=str(ticket_id),
            agent_email=expert_email,
            agent_name=expert_name,
            final=False,
            source="korca_assignment",
        )
        routing_event = await queries.finalize_latest_routing_event_for_ticket(
            session, str(ticket_id)
        )
    return {"assignment": assignment_result, "routing_event": routing_event}


async def _call_aura_agent(
    ticket_id: str, subject: str, content: str, client_name: str
) -> AuraTraceOutcome:
    async def call_aura_agent() -> dict:
        return await route_with_aura_agent(
            subject=subject,
            content=content,
            client_name=client_name,
            current_ticket_id=ticket_id,
        )

    trace_outcome = await trace_aura_route_call(
        call_aura_agent,
        ticket_id=ticket_id,
        subject=subject,
        content=content,
        client_name=client_name,
    )

    if trace_outcome.trace_id:
        async with db_context() as session:
            await session.run(
                """
                MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
                SET t.aura_trace_id = $trace_id,
                    t.aura_suggestion_updated_at = toString(datetime())
                """,
                id=ticket_id,
                trace_id=trace_outcome.trace_id,
            )

    if trace_outcome.error:
        logger.warning(
            "aura_agent_error",
            ticket_id=ticket_id,
            trace_id=trace_outcome.trace_id,
            error=str(trace_outcome.error),
        )
        async with db_context() as session:
            await queries.set_ticket_aura_routing_status(
                session,
                ticket_id=ticket_id,
                status="failed",
                error=str(trace_outcome.error),
            )
        raise AuraAgentError(f"Aura agent error: {trace_outcome.error}")

    return trace_outcome


async def _apply_teamwork_action(
    ticket_id: str,
    routing_mode: str,
    expert_email: str,
    expert_name: str | None,
) -> tuple[str, str | None, str | None]:
    action = "stored"
    assigned_email: str | None = None
    assigned_name: str | None = None

    if routing_mode == "auto_comment":
        try:
            await tw.post_private_note(
                ticket_id=_teamwork_ticket_id(ticket_id),
                message=_aura_suggestion_note(expert_name, expert_email),
                mention_email=expert_email,
                mention_name=expert_name,
            )
            action = "posted_comment"
        except ValueError:
            # Agent not found in Teamwork (e.g. staging account) — post without @mention
            try:
                await tw.post_private_note(
                    ticket_id=_teamwork_ticket_id(ticket_id),
                    message=_aura_suggestion_note(expert_name, expert_email),
                )
                action = "posted_comment"
                logger.warning(
                    "aura_mention_skipped_agent_not_found",
                    expert_email=expert_email,
                    ticket_id=ticket_id,
                )
            except Exception as exc:
                err = str(exc)
                logger.warning(
                    "aura_teamwork_note_failed",
                    expert_email=expert_email,
                    ticket_id=ticket_id,
                    error=err,
                )
                async with db_context() as session:
                    await session.run(
                        _SET_TEAMWORK_ACTION_ERROR,
                        id=ticket_id,
                        err=f"Could not post note to Teamwork: {err}",
                    )
        except Exception as exc:
            err = str(exc)
            logger.warning(
                "aura_teamwork_note_failed",
                expert_email=expert_email,
                ticket_id=ticket_id,
                error=err,
            )
            async with db_context() as session:
                await session.run(
                    _SET_TEAMWORK_ACTION_ERROR,
                    id=ticket_id,
                    err=f"Could not post note to Teamwork: {err}",
                )
    elif routing_mode == "auto_assign":
        try:
            await tw.assign_ticket_to_expert(
                ticket_id=_teamwork_ticket_id(ticket_id),
                expert_email=expert_email,
            )
            action = "assigned"
            assigned_email, assigned_name = expert_email, expert_name
        except ValueError:
            # Agent not found — try fallback if configured (e.g. staging test account)
            fallback = settings.teamwork_fallback_agent_email
            if fallback and fallback.lower() != expert_email.lower():
                try:
                    await tw.assign_ticket_to_expert(
                        ticket_id=_teamwork_ticket_id(ticket_id),
                        expert_email=fallback,
                    )
                    action = "assigned"
                    assigned_email = fallback
                    assigned_name = _fallback_teamwork_expert_name(fallback)
                    logger.warning(
                        "aura_assign_used_fallback",
                        suggested_email=expert_email,
                        fallback_email=fallback,
                        ticket_id=ticket_id,
                    )
                except Exception as exc2:
                    err = str(exc2)
                    logger.warning(
                        "aura_teamwork_assign_failed",
                        expert_email=fallback,
                        ticket_id=ticket_id,
                        error=err,
                    )
                    async with db_context() as session:
                        await session.run(
                            _SET_TEAMWORK_ACTION_ERROR,
                            id=ticket_id,
                            err=f"Could not assign in Teamwork: {err}",
                        )
            else:
                logger.warning(
                    "aura_teamwork_assign_failed_no_fallback",
                    expert_email=expert_email,
                    ticket_id=ticket_id,
                )
                async with db_context() as session:
                    await session.run(
                        _SET_TEAMWORK_ACTION_ERROR,
                        id=ticket_id,
                        err=(
                            f"Teamwork agent not found for {expert_email} "
                            "and no fallback configured"
                        ),
                    )
        except Exception as exc:
            err = str(exc)
            logger.warning(
                "aura_teamwork_assign_failed",
                expert_email=expert_email,
                ticket_id=ticket_id,
                error=err,
            )
            async with db_context() as session:
                await session.run(
                    _SET_TEAMWORK_ACTION_ERROR,
                    id=ticket_id,
                    err=f"Could not assign in Teamwork: {err}",
                )

    if action == "assigned" and assigned_email:
        try:
            await tw.post_private_note(
                ticket_id=_teamwork_ticket_id(ticket_id),
                message=_assignment_note(assigned_name, assigned_email),
                mention_email=assigned_email,
                mention_name=assigned_name,
            )
        except Exception as exc:
            err = str(exc)
            logger.warning(
                "aura_teamwork_assignment_note_failed",
                expert_email=assigned_email,
                ticket_id=ticket_id,
                error=err,
            )
            async with db_context() as session:
                await session.run(
                    _SET_TEAMWORK_ACTION_ERROR,
                    id=ticket_id,
                    err=f"Could not post assignment note to Teamwork: {err}",
                )

    return action, assigned_email, assigned_name


async def _record_routing_event(
    ticket_id: str,
    expert_email: str | None,
    expert_name: str | None,
    confidence: str,
    mode: str,
    action: str,
    trace_id: str | None,
) -> dict:
    async with db_context() as session:
        return await queries.record_aura_routing_event(
            session,
            ticket_id=ticket_id,
            expert_email=expert_email,
            expert_name=expert_name,
            confidence=confidence,
            mode=mode,
            action=action,
            trace_id=trace_id,
        )


async def route_ticket_with_aura(ticket_id: str, apply_teamwork_actions: bool) -> dict:
    """Route a ticket using the Neo4j Aura agent.

    Fetches the ticket, sends subject + first message to the Aura-hosted
    triage agent, and returns the extracted expert recommendation.
    """
    async with db_context() as session:
        ticket = await queries.get_ticket_full(session, ticket_id)
        if not ticket:
            raise TicketNotFoundError("Ticket not found")
        experts_raw = await session.run("MATCH (u:User) RETURN u.email AS email, u.name AS name")
        experts = {
            (r["email"] or "").lower(): r["name"] for r in await experts_raw.data() if r["email"]
        }
        configured_routing_mode = await queries.get_teamwork_routing_mode(session)
        routing_mode = configured_routing_mode if apply_teamwork_actions else "manual"

    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(
            session,
            ticket_id=ticket_id,
            status="running",
        )

    subject = ticket.get("subject") or ""
    content = ticket.get("request_content") or ticket.get("content") or ticket.get("preview") or ""
    client_name = (
        ticket.get("client_name")
        or ticket.get("client_domain")
        or ticket.get("client_display_name")
        or ""
    )

    trace_outcome = await _call_aura_agent(
        ticket_id=ticket_id,
        subject=subject,
        content=content,
        client_name=client_name,
    )

    result = trace_outcome.response or {}
    expert_email = _parse_aura_expert_email(result)
    expert_name = experts.get(expert_email) if expert_email else None
    logger.info("aura_route_extracted", expert_email=expert_email, expert_name=expert_name)

    # Write routing result to graph first, before any Teamwork side-effects
    action = "no_recommendation" if not expert_email else "stored"
    async with db_context() as session:
        if expert_email:
            await session.run(
                """
                MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
                SET t.aura_suggestion_email = $email,
                    t.aura_suggestion_confidence = $confidence,
                    t.routing_status = 'suggested',
                    t.aura_routing_error = null,
                    t.teamwork_action_error = null,
                    t.aura_suggestion_updated_at = toString(datetime()),
                    t.aura_routing_updated_at = toString(datetime())
                """,
                id=ticket_id,
                email=expert_email,
                confidence="aura",
            )
        else:
            await session.run(
                """
                MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
                SET t.routing_status = 'no_recommendation',
                    t.aura_routing_error = 'Aura agent did not return a recommended expert email',
                    t.aura_suggestion_updated_at = toString(datetime()),
                    t.aura_routing_updated_at = toString(datetime())
                REMOVE t.aura_suggestion_email, t.aura_suggestion_confidence
                """,
                id=ticket_id,
            )

    if not expert_email:
        routing_event = await _record_routing_event(
            ticket_id=ticket_id,
            expert_email=expert_email,
            expert_name=expert_name,
            confidence="aura",
            mode=routing_mode,
            action=action,
            trace_id=trace_outcome.trace_id,
        )
        logger.warning(
            "aura_route_no_recommendation",
            ticket_id=ticket_id,
            trace_id=trace_outcome.trace_id,
        )
        raise AuraAgentError(
            "Aura agent did not return a recommended expert email",
        )

    # Teamwork side-effects (post note / assign)
    action, assigned_email, assigned_name = await _apply_teamwork_action(
        ticket_id=ticket_id,
        routing_mode=routing_mode,
        expert_email=expert_email,
        expert_name=expert_name,
    )

    routing_event = await _record_routing_event(
        ticket_id=ticket_id,
        expert_email=expert_email,
        expert_name=expert_name,
        confidence="aura",
        mode=routing_mode,
        action=action,
        trace_id=trace_outcome.trace_id,
    )

    if action == "assigned" and assigned_email:
        await _mirror_korca_assignment(ticket_id, assigned_email, assigned_name)

    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(
            session,
            ticket_id=ticket_id,
            status="suggested",
            error=None,
        )

    return {
        "ticket_id": ticket_id,
        "expert_email": expert_email,
        "expert_name": expert_name,
        "routing_event": routing_event,
    }


async def route_ticket_with_aura_automated(ticket_id: str) -> dict:
    """Route a queued ticket and apply the configured Teamwork routing mode."""
    return await route_ticket_with_aura(ticket_id, apply_teamwork_actions=True)
