"""Teamwork import, sync, and Teamwork-ticket management routes."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from app.api.routes.tickets import TicketResponse
from app.config import settings
from app.db import queries
from app.db.connection import db_context
from app.services import teamwork as tw
from app.services.notifications import push_notification
from app.services.redis_cache import (
    CACHE_KEY_EXPERTS,
    CACHE_KEY_FILTERS,
    get_cached_data,
    invalidate_cache,
    set_cached_data,
)
from app.services.redis_lock import acquire_lock, release_lock
from app.services.teamwork_import_status import (
    TEAMWORK_IMPORT_LOCK,
    TEAMWORK_IMPORT_LOCK_TTL,
    TERMINAL_IMPORT_STATUSES,
    TeamworkImportProgress,
    get_effective_import_progress,
    is_full_import_running,
    set_progress,
)
from app.services.teamwork_sync import (
    _extract_ticket,
    _is_blocked_subject,
    _persist_imported_teamwork_ticket,
    _subject_blocklist_prefixes,
    _summarize_and_embed_ticket,
    run_teamwork_sync_now,
    sync_single_ticket,
)

logger = structlog.get_logger()
router = APIRouter()

_IMPORT_RUNNING_DETAIL = "Full Teamwork import running"
_TEAMWORK_IMPORT_PROGRESS_MAX_EVENTS = 300


class RoutingModeRequest(BaseModel):
    mode: str


class AutoSyncRequest(BaseModel):
    enabled: bool
    interval_seconds: int


class TeamworkFilterOptionsResponse(BaseModel):
    clients: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    inboxes: list[str] = Field(default_factory=list)


class TeamworkAutoSyncResponse(BaseModel):
    enabled: bool
    interval_seconds: int


class TeamworkSyncStateResponse(BaseModel):
    """Compatible with the frontend `TeamworkSyncState`, but more tolerant. The
    state node is returned via `s {.*}`, so unknown fields are preserved
    (`extra="allow"`) and known fields stay optional."""

    model_config = ConfigDict(extra="allow")

    source: str | None = None
    name: str | None = None
    cursor: str | None = None
    status: str | None = None
    error: str | None = None
    last_run_at: str | None = None
    processed: int | None = None
    imported: int | None = None
    updated: int | None = None
    protected_skipped: int | None = None
    failed: int | None = None


class CountResponse(BaseModel):
    count: int


class DeletedResponse(BaseModel):
    deleted: int


class RoutingModeResponse(BaseModel):
    mode: str
    # Whether the staging expert (post/assign-staging-expert) is usable. The
    # backend requires the email; the name is optional, so gate on the email.
    staging_expert_configured: bool = False


def _staging_expert_configured() -> bool:
    return bool(settings.teamwork_staging_expert_email.strip())


class SyncStateResponse(BaseModel):
    initialized: bool
    state: dict[str, Any] | None


class PurgeBlockedPreviewResponse(BaseModel):
    count: int
    samples: list[str]
    filter: str


class ImportStartResponse(BaseModel):
    status: Literal["started", "already_running"]


class ImportStatusResponse(BaseModel):
    tickets_in_graph: int
    import_running: bool
    last_imported_at: str | None
    progress: TeamworkImportProgress | None = None


class ReimportResponse(BaseModel):
    status: str
    ticket_id: int
    subject: str


class SingleSyncResponse(BaseModel):
    status: str
    imported: int
    updated: int
    protected_skipped: int
    blocked: int
    failed: int


class FailedTicket(BaseModel):
    ticket_id: str
    error: str


class TeamworkSyncResult(BaseModel):
    status: str
    cursor: str
    processed: int
    imported: int
    updated: int
    protected_skipped: int
    failed: int
    blocked: int
    needs_routing: int
    failed_ticket_ids: list[str]
    failed_ticket_errors: list[FailedTicket]


def _enqueue_aura_routing_job(ticket_id: str) -> None:
    from app.worker import process_aura_routing_ticket

    process_aura_routing_ticket.delay(str(ticket_id))


def _enqueue_full_teamwork_import(lock_token: str) -> None:
    from app.worker import run_full_teamwork_import

    run_full_teamwork_import.delay(lock_token)


async def _full_import_running_detail() -> str | None:
    if await is_full_import_running():
        return _IMPORT_RUNNING_DETAIL
    return None


@router.post("/teamwork", responses={500: {"description": "Could not enqueue Teamwork import"}})
async def start_teamwork_import() -> ImportStartResponse:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        lock_token = await acquire_lock(r, TEAMWORK_IMPORT_LOCK, TEAMWORK_IMPORT_LOCK_TTL)
        if not lock_token:
            return ImportStartResponse(status="already_running")

        started_at = datetime.now(UTC).isoformat()
        try:
            await set_progress(
                status="queued",
                message="Import queued...",
                started_at=started_at,
            )
            _enqueue_full_teamwork_import(lock_token)
        except Exception as exc:
            message = f"Could not enqueue Teamwork import: {exc}"
            await set_progress(
                status="error",
                message=message,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                error=message,
            )
            await release_lock(r, TEAMWORK_IMPORT_LOCK, lock_token)
            raise HTTPException(status_code=500, detail=message) from exc

    return ImportStartResponse(status="started")


@router.get("/teamwork/progress")
async def teamwork_import_progress() -> EventSourceResponse:
    return EventSourceResponse(_teamwork_import_progress_events())


async def _teamwork_import_progress_events(max_events: int = _TEAMWORK_IMPORT_PROGRESS_MAX_EVENTS):
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        for _ in range(max_events):
            progress, _import_running = await get_effective_import_progress(redis)
            yield {"data": progress.model_dump_json(exclude_none=True)}
            if progress.status in TERMINAL_IMPORT_STATUSES:
                break
            await asyncio.sleep(1)


@router.get("/teamwork/filters")
async def teamwork_filter_options() -> TeamworkFilterOptionsResponse:
    cached = await get_cached_data(CACHE_KEY_FILTERS)
    if isinstance(cached, dict):
        return TeamworkFilterOptionsResponse.model_validate(cached)
    async with db_context() as session:
        data = await queries.get_teamwork_filter_options(session)
    await set_cached_data(CACHE_KEY_FILTERS, data)
    return TeamworkFilterOptionsResponse.model_validate(data)


@router.get("/teamwork/tickets")
async def list_teamwork_tickets(
    offset: int = 0,
    limit: int = 20,
    client: str = "",
    agent: str = "",
    inbox: str = "",
    search: str = "",
    mismatch_only: bool = False,
    unrouted_only: bool = False,
    sort_by_status: bool = False,
    imported_after: str = "",
) -> list[TicketResponse]:
    async with db_context() as session:
        rows = await queries.list_tickets(
            session,
            offset=offset,
            limit=limit,
            source_system="teamwork",
            client_filter=client,
            agent_filter=agent,
            inbox_filter=inbox,
            search=search,
            mismatch_only=mismatch_only,
            unrouted_only=unrouted_only,
            sort_by_status=sort_by_status,
            imported_after=imported_after,
        )
    return [TicketResponse.model_validate(row) for row in rows]


@router.get("/teamwork/tickets/count")
async def count_teamwork_tickets(
    client: str = "",
    agent: str = "",
    inbox: str = "",
    search: str = "",
    mismatch_only: bool = False,
    unrouted_only: bool = False,
    imported_after: str = "",
) -> CountResponse:
    async with db_context() as session:
        n = await queries.count_tickets_filtered(
            session,
            source_system="teamwork",
            client_filter=client,
            agent_filter=agent,
            inbox_filter=inbox,
            search=search,
            mismatch_only=mismatch_only,
            unrouted_only=unrouted_only,
            imported_after=imported_after,
        )
    return CountResponse(count=n)


@router.delete(
    "/teamwork/tickets",
    responses={409: {"description": _IMPORT_RUNNING_DETAIL}},
)
async def clear_teamwork_tickets() -> DeletedResponse:
    if detail := await _full_import_running_detail():
        raise HTTPException(status_code=409, detail=detail)
    async with db_context() as session:
        n = await queries.delete_tickets_by_source(session, "teamwork")
    logger.info("Cleared Teamwork tickets", count=n)
    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)
    return DeletedResponse(deleted=n)


@router.get("/teamwork/routing-mode")
async def get_teamwork_routing_mode() -> RoutingModeResponse:
    async with db_context() as session:
        mode = await queries.get_teamwork_routing_mode(session)
    return RoutingModeResponse(
        mode=mode,
        staging_expert_configured=_staging_expert_configured(),
    )


@router.put(
    "/teamwork/routing-mode", responses={422: {"description": "Invalid routing mode value"}}
)
async def set_teamwork_routing_mode(body: RoutingModeRequest) -> RoutingModeResponse:
    async with db_context() as session:
        try:
            result = await queries.set_teamwork_routing_mode(session, body.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RoutingModeResponse(
        mode=str(result["mode"]),
        staging_expert_configured=_staging_expert_configured(),
    )


@router.get("/teamwork/auto-sync")
async def get_teamwork_auto_sync() -> TeamworkAutoSyncResponse:
    async with db_context() as session:
        data = await queries.get_teamwork_auto_sync_settings(session)
    return TeamworkAutoSyncResponse.model_validate(data)


@router.put("/teamwork/auto-sync", responses={422: {"description": "Invalid auto-sync settings"}})
async def set_teamwork_auto_sync(body: AutoSyncRequest) -> TeamworkAutoSyncResponse:
    async with db_context() as session:
        try:
            data = await queries.set_teamwork_auto_sync_settings(
                session,
                enabled=body.enabled,
                interval_seconds=body.interval_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TeamworkAutoSyncResponse.model_validate(data)


@router.get("/teamwork/sync-state")
async def get_teamwork_sync_state() -> SyncStateResponse:
    async with db_context() as session:
        state = await queries.get_teamwork_update_sync_state(session)
    return SyncStateResponse(initialized=state is not None, state=state)


@router.post("/teamwork/sync/bootstrap", response_model_exclude_none=True)
async def bootstrap_teamwork_sync() -> TeamworkSyncStateResponse:
    """Initialize update sync at the current time to protect corrected historical tickets."""
    async with db_context() as session:
        state = await queries.bootstrap_teamwork_update_sync_state(session)
    return TeamworkSyncStateResponse.model_validate(state)


@router.post(
    "/teamwork/sync-now",
    responses={409: {"description": _IMPORT_RUNNING_DETAIL}},
)
async def sync_teamwork_now() -> TeamworkSyncResult:
    """Fetch Teamwork tickets changed after the update cursor and upsert safe changes."""
    if detail := await _full_import_running_detail():
        raise HTTPException(status_code=409, detail=detail)
    res = await run_teamwork_sync_now(enqueue_aura_routing_job=_enqueue_aura_routing_job)
    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)
    changed = res.get("updated", 0) + res.get("imported", 0)
    if changed > 0:
        await push_notification(
            type="sync",
            message=f"Manual sync complete: {res.get('imported', 0)} imported, {res.get('updated', 0)} updated",
            status="info",
        )
    return TeamworkSyncResult(**res)


@router.get("/teamwork/purge-blocked/preview")
async def purge_blocked_preview(prefix: str = "") -> PurgeBlockedPreviewResponse:
    """Return a count and sample of tickets that would be deleted by purge-blocked.

    If `prefix` is provided, use it as the filter; otherwise use the default blocklist.
    """
    if prefix:
        query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND toLower(t.subject) STARTS WITH toLower($prefix)
        RETURN t.id AS id, t.subject AS subject
        """
        params: dict[str, object] = {"prefix": prefix}
        filter_desc = f'subject starts with "{prefix}"'
    else:
        query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND ANY(pref IN $prefixes WHERE toLower(t.subject) STARTS WITH toLower(pref))
        RETURN t.id AS id, t.subject AS subject
        """
        prefixes = _subject_blocklist_prefixes()
        params = {"prefixes": list(prefixes)}
        filter_desc = "subject starts with: " + ", ".join(f'"{p}"' for p in prefixes)

    async with db_context() as session:
        result = await session.run(query, **params)
        matches = await result.data()

    samples = [r["subject"] for r in matches]
    return PurgeBlockedPreviewResponse(count=len(matches), samples=samples, filter=filter_desc)


@router.post(
    "/teamwork/purge-blocked",
    responses={409: {"description": _IMPORT_RUNNING_DETAIL}},
)
async def purge_blocked_tickets(prefix: str = "", block: bool = False) -> DeletedResponse:
    """Delete all tickets whose subject matches the blocked-subject filter.

    If `prefix` is provided, use it as the filter; otherwise use the default blocklist.
    If `block` is true, also add deleted ticket IDs to the BlockedTicket list.
    """
    if detail := await _full_import_running_detail():
        raise HTTPException(status_code=409, detail=detail)
    if prefix:
        id_query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND toLower(t.subject) STARTS WITH toLower($prefix)
        RETURN collect(DISTINCT t.id) AS ids
        """
        delete_query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND toLower(t.subject) STARTS WITH toLower($prefix)
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        WITH t, e
        DETACH DELETE t, e
        RETURN count(DISTINCT t) AS deleted
        """
        params: dict[str, object] = {"prefix": prefix}
    else:
        id_query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND ANY(pref IN $prefixes WHERE toLower(t.subject) STARTS WITH toLower(pref))
        RETURN collect(DISTINCT t.id) AS ids
        """
        delete_query = """
        MATCH (t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND ANY(pref IN $prefixes WHERE toLower(t.subject) STARTS WITH toLower(pref))
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        WITH t, e
        DETACH DELETE t, e
        RETURN count(DISTINCT t) AS deleted
        """
        params = {"prefixes": list(_subject_blocklist_prefixes())}

    async with db_context() as session:
        blocked_ids: list[int] = []
        if block:
            id_result = await session.run(id_query, **params)
            id_record = await id_result.single()
            blocked_ids = id_record["ids"] if id_record else []

        result = await session.run(delete_query, **params)
        record = await result.single()
        deleted = record["deleted"] if record else 0

        if blocked_ids:
            await session.run(
                "UNWIND $ids AS id MERGE (:BlockedTicket {id: id})",
                ids=blocked_ids,
            )

    logger.info("Purged blocked tickets", deleted=deleted, block=block, prefix=prefix or "default")
    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)
    return DeletedResponse(deleted=deleted)


@router.get("/teamwork/status")
async def import_teamwork_status() -> ImportStatusResponse:
    async with db_context() as session:
        count = await queries.count_tickets(session, source_system="teamwork")
        result = await session.run(
            "MATCH (t:Ticket {source_system: 'teamwork'}) WHERE t.imported_at IS NOT NULL "
            "RETURN MAX(t.imported_at) AS last_imported_at"
        )
        row = await result.single()
        last_imported_at = row["last_imported_at"] if row else None
    progress, import_running = await get_effective_import_progress()
    return ImportStatusResponse(
        tickets_in_graph=count,
        import_running=import_running,
        last_imported_at=last_imported_at,
        progress=progress,
    )


@router.post(
    "/teamwork/tickets/{ticket_id}/reimport",
    responses={
        400: {"description": "Invalid Teamwork ticket ID"},
        409: {"description": _IMPORT_RUNNING_DETAIL},
        404: {"description": "Ticket not found in Teamwork"},
    },
)
async def reimport_teamwork_ticket(ticket_id: str) -> ReimportResponse:
    """Re-fetch a single Teamwork ticket and reprocess it through the full pipeline."""
    if detail := await _full_import_running_detail():
        raise HTTPException(status_code=409, detail=detail)
    try:
        raw_id = int(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Teamwork ticket ID")

    ticket_detail, threads = await asyncio.gather(
        tw.fetch_ticket_full(raw_id),
        tw.fetch_ticket_threads(raw_id),
    )
    if not ticket_detail:
        raise HTTPException(status_code=404, detail="Ticket not found in Teamwork")

    # Threads are embedded in the ticket detail response — use those directly
    embedded_threads = ticket_detail.get("threads") or []
    if not threads and embedded_threads:
        threads = embedded_threads

    ticket = _extract_ticket(ticket_detail, ticket_detail, threads)

    if _is_blocked_subject(ticket.get("subject", "")):
        async with db_context() as session:
            await queries.delete_ticket(session, ticket_id)
        logger.info(
            "Blocked ticket removed on reimport",
            ticket_id=raw_id,
            subject=ticket.get("subject", "")[:80],
        )
        return ReimportResponse(status="removed", ticket_id=raw_id, subject=ticket["subject"])

    await _summarize_and_embed_ticket(ticket, raw_id, source="teamwork_reimport")

    async with db_context() as session:
        await _persist_imported_teamwork_ticket(session, ticket)

    logger.info("Single ticket reimported", ticket_id=raw_id, subject=ticket["subject"])
    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)
    return ReimportResponse(status="ok", ticket_id=raw_id, subject=ticket["subject"])


@router.post(
    "/teamwork/tickets/{ticket_id}/sync",
    responses={
        400: {"description": "Invalid Teamwork ticket ID"},
        409: {"description": _IMPORT_RUNNING_DETAIL},
        404: {"description": "Ticket not found in Teamwork"},
    },
)
async def sync_teamwork_ticket(ticket_id: str) -> SingleSyncResponse:
    """Sync one ticket through the normal sync path (reuses existing content/embedding)."""
    if detail := await _full_import_running_detail():
        raise HTTPException(status_code=409, detail=detail)
    try:
        int(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Teamwork ticket ID")

    result = await sync_single_ticket(ticket_id, enqueue_aura_routing_job=_enqueue_aura_routing_job)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Ticket not found in Teamwork")

    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)
    return SingleSyncResponse(
        status=result["status"],
        imported=result["imported"],
        updated=result["updated"],
        protected_skipped=result["protected_skipped"],
        blocked=result["blocked"],
        failed=result["failed"],
    )
