"""Teamwork sync orchestration service.

Contains Teamwork data-processing helpers and the sync loop so both route
handlers and the Celery worker can import from here instead of creating a
worker → routes import cycle.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from html.parser import HTMLParser

import structlog
from redis.asyncio import Redis

from app.config import settings
from app.db import queries
from app.db.connection import db_context
from app.exceptions import SyncConflictError, SyncNotBootstrappedError
from app.services import teamwork as tw
from app.services.embeddings import embed_query
from app.services.gatekeeper import gate_and_persist_ticket
from app.services.llm import summarize_ticket
from app.services.redis_cache import CACHE_KEY_EXPERTS, CACHE_KEY_FILTERS, invalidate_cache
from app.services.redis_lock import acquire_lock, release_lock

logger = structlog.get_logger()

_SYNC_LOCK = "korca:teamwork_sync_lock"
_SYNC_LOCK_TTL = 600  # 10 min — auto-expires if process crashes mid-sync

_SYSTEM_THREAD_TYPES = {"forward", "automation", "status", "note"}
_BLOCKED_TEAMWORK_STATUSES = {"spam", "deleted", "merged"}
FullImportProgressWriter = Callable[..., Awaitable[object]]


def _subject_blocklist_prefixes() -> tuple[str, ...]:
    """Lower-cased subject prefixes to skip on import (TEAMWORK_SUBJECT_BLOCKLIST)."""
    return tuple(p.lower() for p in settings.teamwork_subject_blocklist)


def _personal_domains() -> set[str]:
    """Configured domains never treated as client organisations."""
    return {d.lower().strip() for d in settings.teamwork_personal_domains if d.strip()}


class _MLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, d: str) -> None:
        self._parts.append(d)


def _strip_html(text: str) -> str:
    import re

    s = _MLStripper()
    s.feed(text)
    raw = "".join(s._parts)
    return re.sub(r"\s+", " ", raw).strip()


def _is_blocked_subject(subject: str) -> bool:
    return subject.lower().startswith(_subject_blocklist_prefixes())


def _is_closed_status(status: str | None) -> bool:
    return (status or "").lower() in {"closed", "solved", "resolved"}


def _is_blocked_status(status: str | None) -> bool:
    return (status or "").strip().lower() in _BLOCKED_TEAMWORK_STATUSES


def _qualifies_for_embedding(ticket: dict) -> bool:
    """Only closed tickets with an assignee and a known client become routing knowledge.

    Mirrors the gatekeeper promotion rules so the vector index contains only
    promotable tickets — open or unassigned tickets must not crowd routing
    candidates out of the Semantic Ticket Finder top-K.
    """
    if not _is_closed_status(ticket.get("status")):
        return False
    if not (ticket.get("agent_email") or "").strip():
        return False
    client = ticket.get("client") or {}
    return bool((client.get("name") or "").strip() or (client.get("domain") or "").strip())


def _thread_type(thread: dict) -> str:
    thread_type = thread.get("threadType")
    if isinstance(thread_type, dict):
        value = thread_type.get("name") or thread_type.get("type") or thread_type.get("id")
        return str(value or "").lower()
    if thread_type:
        return str(thread_type).lower()
    return str(thread.get("type") or "").lower()


def _build_raw_content(ticket: dict, ticket_detail: dict, threads: list[dict]) -> str:
    """Full thread — all non-system messages concatenated. Stored for reference only."""
    parts = [ticket.get("subject", "")]

    sorted_threads = sorted(threads, key=lambda t: t.get("id", 0))
    for thread in sorted_threads:
        t_type = _thread_type(thread)
        if t_type in _SYSTEM_THREAD_TYPES:
            continue
        body = thread.get("body") or thread.get("textBody") or ""
        if body:
            parts.append(_strip_html(body)[:1500])

    if len(parts) == 1 and ticket_detail.get("preview"):
        parts.append(ticket_detail["preview"])

    return "\n\n".join(p for p in parts if p)


def _build_request_content(ticket: dict, ticket_detail: dict, threads: list[dict]) -> str:
    """Subject + first non-system message only — used for embeddings and routing.

    Using only the first message ensures:
    - No agent name/mention pollution from replies
    - Identical input format to live webhook tickets (which have no replies yet)
    - Clean topic signal uncontaminated by discussion
    """
    parts = [ticket.get("subject", "")]

    sorted_threads = sorted(threads, key=lambda t: t.get("id", 0))
    for thread in sorted_threads:
        t_type = _thread_type(thread)
        if t_type in _SYSTEM_THREAD_TYPES:
            continue
        body = thread.get("body") or thread.get("textBody") or ""
        if body:
            parts.append(_strip_html(body)[:2000])
            break  # first non-system message only

    if len(parts) == 1 and ticket_detail.get("preview"):
        parts.append(ticket_detail["preview"])

    return "\n\n".join(p for p in parts if p)


def _extract_client(raw: dict, ticket_detail: dict) -> dict | None:
    """Extract company name and domain from ticket. Returns None if nothing useful."""
    fields_name = ""
    for f in ticket_detail.get("fields") or []:
        if f.get("agentLabel") == "Customer Name" and (f.get("textValue") or "").strip():
            fields_name = f["textValue"].strip()
            break

    company = raw.get("company") or {}
    company_name = company.get("name", "").strip() if isinstance(company, dict) else ""

    name = fields_name or company_name

    customer_email = (raw.get("customer") or {}).get("email", "")
    domain = ""
    if "@" in customer_email:
        d = customer_email.split("@")[-1].lower()
        if d not in _personal_domains():
            domain = d

    if not name and not domain:
        return None

    return {"name": name, "domain": domain}


def _extract_ticket(raw: dict, ticket_detail: dict, threads: list[dict]) -> dict:
    assigned = raw.get("assignedTo") or {}
    tags_raw = raw.get("tags") or []
    tags = [t["name"] if isinstance(t, dict) else t for t in tags_raw]

    agent_email = None
    agent_name = ""
    if isinstance(assigned, dict):
        agent_email = (assigned.get("email") or "").strip().lower() or None
        agent_name = f"{assigned.get('firstName', '')} {assigned.get('lastName', '')}".strip()

    return {
        "id": raw["id"],
        "subject": raw.get("subject", ""),
        "preview": raw.get("preview", ""),
        "status": raw.get("status", "active"),
        "source": raw.get("source", ""),
        "source_system": "teamwork",
        "ticket_type": (ticket_detail.get("type") or raw.get("type") or "").strip() or None,
        "inbox_name": (ticket_detail.get("inboxName") or "").strip() or None,
        "created_at": raw.get("createdAt"),
        "resolved_at": None,
        "tags": tags,
        "agent_email": agent_email,
        "agent_name": agent_name,
        "client": _extract_client(raw, ticket_detail),
        "content": _build_request_content(raw, ticket_detail, threads),
        "raw_content": _build_raw_content(raw, ticket_detail, threads),
    }


async def _persist_imported_teamwork_ticket(session, ticket: dict) -> None:
    await queries.upsert_ticket(session, ticket)
    await queries.upsert_teamwork_assigned_to(
        session,
        ticket_id=str(ticket["id"]),
        agent_email=ticket.get("agent_email"),
        agent_name=ticket.get("agent_name"),
        final=_is_closed_status(ticket.get("status")),
        protected=_is_closed_status(ticket.get("status")) and bool(ticket.get("agent_email")),
        source="teamwork_import",
    )
    await gate_and_persist_ticket(
        session,
        ticket,
        require_assignee=True,
        require_closed=True,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def _full_import_start_state() -> tuple[str | None, bool, bool]:
    async with db_context() as session:
        latest_ticket_timestamp = await queries.get_latest_ticket_timestamp(session, "teamwork")
        sync_state = await queries.get_teamwork_update_sync_state(session)
    has_update_cursor = bool(sync_state and sync_state.get("cursor"))
    initial_import = latest_ticket_timestamp is None or not has_update_cursor
    return latest_ticket_timestamp, initial_import, has_update_cursor


async def _report_full_import_progress(
    *,
    set_progress: FullImportProgressWriter,
    message: str,
    processed: int,
    imported: int,
    skipped: int,
    failed: int,
    total: int | None,
    started_at: str,
) -> None:
    await set_progress(
        status="running",
        message=message,
        processed=processed,
        imported=imported,
        skipped=skipped,
        failed=failed,
        total=total,
        started_at=started_at,
    )


def _should_skip_raw_full_import_ticket(raw: dict, created_after: str | None) -> bool:
    if created_after and (raw.get("createdAt") or "") <= created_after:
        return True

    if _is_blocked_status(raw.get("status")):
        return True

    if _is_blocked_subject(raw.get("subject", "")):
        logger.info(
            "ticket_blocked_subject",
            ticket_id=raw["id"],
            subject=raw.get("subject", "")[:80],
        )
        return True

    return False


async def _should_skip_stored_full_import_ticket(ticket_id: int) -> bool:
    async with db_context() as session:
        if await queries.is_ticket_blocked(session, ticket_id):
            return True
        return bool(await queries.ticket_exists(session, ticket_id))


async def _fetch_full_import_ticket_detail(raw: dict, ticket_id: int) -> tuple[dict, list]:
    ticket_detail = raw
    threads = raw.get("threads") or []
    if not threads:
        ticket_detail, threads = await asyncio.gather(
            tw.fetch_ticket_full(ticket_id),
            tw.fetch_ticket_threads(ticket_id),
        )
    if not threads:
        threads = ticket_detail.get("threads") or []
    return ticket_detail, threads


async def _summarize_and_embed_full_import_ticket(ticket: dict, ticket_id: int) -> None:
    await _summarize_and_embed_ticket(ticket, ticket_id, source="teamwork_import")
    if ticket.get("embedding"):
        await asyncio.sleep(1.0)


async def _import_full_teamwork_ticket(raw: dict, created_after: str | None) -> bool:
    ticket_id = int(raw["id"])
    if _should_skip_raw_full_import_ticket(raw, created_after):
        return False
    if await _should_skip_stored_full_import_ticket(ticket_id):
        return False

    ticket_detail, threads = await _fetch_full_import_ticket_detail(raw, ticket_id)
    ticket = _extract_ticket(raw, ticket_detail, threads)
    await _summarize_and_embed_full_import_ticket(ticket, ticket_id)

    async with db_context() as session:
        await _persist_imported_teamwork_ticket(session, ticket)
    return True


async def run_full_teamwork_import(*, set_progress: FullImportProgressWriter) -> dict:
    """Import Teamwork tickets in the background and report durable running progress."""
    imported = skipped = failed = 0
    started_at = _utc_now()

    created_after, initial_import, has_update_cursor = await _full_import_start_state()
    mode = f"created after {created_after}" if created_after else "full"
    await _report_full_import_progress(
        set_progress=set_progress,
        message=f"Fetching ticket list ({mode})...",
        processed=0,
        imported=0,
        skipped=0,
        failed=0,
        total=None,
        started_at=started_at,
    )

    tickets = await tw.fetch_all_tickets(created_after=created_after)
    total = len(tickets)
    await _report_full_import_progress(
        set_progress=set_progress,
        message=f"Found {total} tickets",
        processed=0,
        imported=0,
        skipped=0,
        failed=0,
        total=total,
        started_at=started_at,
    )

    for index, raw in enumerate(tickets, 1):
        ticket_id = raw["id"]
        try:
            if await _import_full_teamwork_ticket(raw, created_after):
                imported += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            logger.warning("Failed to import ticket", ticket_id=ticket_id, error=str(exc))
        finally:
            if index % 10 == 0 or index == total:
                await _report_full_import_progress(
                    set_progress=set_progress,
                    message=f"Processed {index}/{total}",
                    processed=index,
                    imported=imported,
                    skipped=skipped,
                    failed=failed,
                    total=total,
                    started_at=started_at,
                )
                await asyncio.sleep(0)

    await invalidate_cache(CACHE_KEY_FILTERS, CACHE_KEY_EXPERTS)

    if not has_update_cursor:
        async with db_context() as session:
            await queries.bootstrap_teamwork_update_sync_state(session)
            logger.info("teamwork_sync_cursor_auto_bootstrapped")

    return {
        "created_after": created_after,
        "initial_import": initial_import,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "total": total,
    }


def _has_processed_request(ticket: dict | None) -> bool:
    if not ticket:
        return False
    return bool(
        (ticket.get("request_content") or "").strip()
        and (ticket.get("content") or "").strip()
        and ticket.get("gemini_embedding")
    )


async def _handle_blocked_status(raw: dict, ticket_id: int | str) -> bool:
    """Return True if a Teamwork status/subject marks the ticket as blocked.

    For subject-blocklist hits the ticket is also deleted from the graph so a
    previously-imported copy doesn't linger.
    """
    if _is_blocked_status(raw.get("status")):
        return True
    if _is_blocked_subject(raw.get("subject", "")):
        async with db_context() as session:
            await queries.delete_ticket(session, str(ticket_id))
        return True
    return False


async def _load_existing_ticket_state(ticket_id: int | str) -> tuple[bool, bool, dict | None]:
    """Return (existed, already_routed, existing_processing_payload)."""
    async with db_context() as session:
        existed = await queries.ticket_exists(session, int(ticket_id))
        already_routed = existed and await queries.has_routing_recommendation(session, ticket_id)
        existing_processing = (
            await queries.get_ticket_processing_payload(session, ticket_id) if existed else None
        )
    return existed, already_routed, existing_processing


async def _resolve_ticket_detail_and_threads(
    raw: dict,
    ticket_id: int | str,
    *,
    already_processed: bool,
) -> tuple[dict, list]:
    """Reuse the webhook payload when it already has threads; otherwise refetch."""
    ticket_detail = raw
    threads = raw.get("threads") or []
    if not already_processed and not threads:
        ticket_detail, threads = await asyncio.gather(
            tw.fetch_ticket_full(int(ticket_id)),
            tw.fetch_ticket_threads(int(ticket_id)),
        )
    if not threads:
        threads = ticket_detail.get("threads") or []
    return ticket_detail, threads


def _reuse_existing_processed_payload(ticket: dict, existing: dict) -> None:
    """In-place hydrate ticket fields from the previously persisted payload.

    A stored embedding is reused only while the ticket still qualifies; if it
    no longer does (e.g. reopened, or embedded before the closed-only rule),
    the upsert scrubs it from the vector index.
    """
    ticket["request_content"] = existing.get("request_content") or ticket["content"]
    ticket["content"] = existing.get("content") or ticket["request_content"]
    ticket["raw_content"] = existing.get("raw_content") or ticket["raw_content"]
    ticket["embedding"] = (
        existing.get("gemini_embedding") if _qualifies_for_embedding(ticket) else None
    )
    ticket["ticket_type"] = ticket["ticket_type"] or existing.get("ticket_type")
    ticket["inbox_name"] = ticket["inbox_name"] or existing.get("inbox_name")


async def _summarize_and_embed_ticket(
    ticket: dict, ticket_id: int | str, *, source: str = "teamwork_sync"
) -> bool:
    """Populate content/request_content/embedding. Return False if request body empty.

    Tickets that don't qualify for embedding (open, unassigned, or without a
    client) keep their raw content and get no embedding, so they stay out of
    the vector index — but the caller must still persist and route them. Once
    such a ticket closes, its null gemini_embedding makes
    _has_processed_request() return False, so the next sync summarizes,
    embeds, and promotes it.
    """
    request_content = ticket["content"]
    if not request_content.strip():
        return False
    ticket["request_content"] = request_content
    if not _qualifies_for_embedding(ticket):
        ticket["embedding"] = None
        return True
    try:
        clean = await summarize_ticket(ticket["subject"], request_content, ticket["status"])
    except Exception as exc:
        logger.warning(
            "teamwork_summarize_failed", ticket_id=ticket_id, source=source, error=str(exc)
        )
        clean = request_content
    ticket["content"] = clean
    ticket["embedding"] = await embed_query(
        request_content,
        context={"ticket_id": str(ticket_id), "source": source},
    )
    return True


async def _persist_synced_ticket(ticket: dict) -> None:
    """Run the four DB writes that move a synced ticket into the graph."""
    async with db_context() as session:
        await queries.upsert_ticket(session, ticket)
        await queries.upsert_teamwork_assigned_to(
            session,
            ticket_id=str(ticket["id"]),
            agent_email=ticket.get("agent_email"),
            agent_name=ticket.get("agent_name"),
            final=_is_closed_status(ticket.get("status")),
            source="teamwork_sync",
        )
        await queries.finalize_latest_routing_event_for_ticket(session, str(ticket["id"]))
        await gate_and_persist_ticket(session, ticket, require_assignee=True, require_closed=True)


async def _queue_aura_routing(ticket_id: str, enqueue: Callable[[str], None]) -> None:
    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(session, ticket_id=ticket_id, status="queued")
    enqueue(ticket_id)


async def _process_changed_ticket(
    raw: dict,
    ticket_id: int | str,
    counts: dict,
    enqueue_aura_routing_job: Callable[[str], None],
) -> None:
    """Process one ticket from the changed-tickets list, updating counts in place."""
    if await _handle_blocked_status(raw, ticket_id):
        counts["blocked"] += 1
        return

    async with db_context() as session:
        if await queries.has_protected_assigned_to(session, ticket_id):
            counts["protected_skipped"] += 1
            return

    existed, already_routed, existing_processing = await _load_existing_ticket_state(ticket_id)
    already_processed = _has_processed_request(existing_processing)
    ticket_detail, threads = await _resolve_ticket_detail_and_threads(
        raw, ticket_id, already_processed=already_processed
    )
    ticket = _extract_ticket(raw, ticket_detail, threads)

    if already_processed and existing_processing:
        _reuse_existing_processed_payload(ticket, existing_processing)
    elif not await _summarize_and_embed_ticket(ticket, ticket_id):
        return

    await _persist_synced_ticket(ticket)
    counts["updated" if existed else "imported"] += 1

    if not _is_closed_status(ticket.get("status")) and not already_routed:
        counts["needs_routing"] += 1
        await _queue_aura_routing(str(ticket["id"]), enqueue_aura_routing_job)


async def _run_sync_loop(
    cursor: str,
    counts: dict,
    enqueue_aura_routing_job: Callable[[str], None],
    failed_ticket_errors: list[dict[str, str]],
) -> str:
    """Iterate changed tickets, processing each. Return the advanced cursor."""
    next_cursor = cursor
    changed_tickets = await tw.fetch_updated_tickets(updated_after=cursor)
    for raw in changed_tickets:
        counts["processed"] += 1
        ticket_id = raw.get("id")
        if ticket_id is None:
            continue
        updated_at = raw.get("updatedAt")
        if updated_at and updated_at > next_cursor:
            next_cursor = updated_at
        try:
            await _process_changed_ticket(raw, ticket_id, counts, enqueue_aura_routing_job)
        except Exception as exc:
            error = str(exc)
            counts["failed"] += 1
            failed_ticket_errors.append({"ticket_id": str(ticket_id), "error": error})
            logger.warning("teamwork_sync_ticket_failed", ticket_id=ticket_id, error=error)
    return next_cursor


def _failed_ticket_ids(failures: list[dict[str, str]]) -> list[str]:
    return [failure["ticket_id"] for failure in failures]


def _failed_ticket_error_messages(failures: list[dict[str, str]]) -> list[str]:
    return [f"{failure['ticket_id']}: {failure['error']}" for failure in failures]


async def run_teamwork_sync_now(*, enqueue_aura_routing_job: Callable[[str], None]) -> dict:
    """Fetch Teamwork tickets changed after the update cursor and upsert safe changes."""
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        lock_token = await acquire_lock(r, _SYNC_LOCK, _SYNC_LOCK_TTL)
        if not lock_token:
            raise SyncConflictError("Teamwork sync already running")

        try:
            async with db_context() as session:
                state = await queries.get_teamwork_update_sync_state(session)
            if not state or not state.get("cursor"):
                raise SyncNotBootstrappedError("Teamwork update sync must be bootstrapped first")

            cursor = str(state["cursor"])
            counts = {
                "processed": 0,
                "imported": 0,
                "updated": 0,
                "protected_skipped": 0,
                "failed": 0,
                "blocked": 0,
                "needs_routing": 0,
            }
            next_cursor = cursor
            failed_ticket_errors: list[dict[str, str]] = []

            try:
                next_cursor = await _run_sync_loop(
                    cursor,
                    counts,
                    enqueue_aura_routing_job,
                    failed_ticket_errors,
                )
                status = "ok" if counts["failed"] == 0 else "partial"
                completion_cursor = next_cursor
                failed_ticket_ids = _failed_ticket_ids(failed_ticket_errors)
                failed_error_messages = _failed_ticket_error_messages(failed_ticket_errors)
                async with db_context() as session:
                    await queries.complete_teamwork_update_sync_state(
                        session,
                        cursor=completion_cursor,
                        status=status,
                        counts=counts,
                        error=None if status == "ok" else f"{counts['failed']} ticket(s) failed",
                        failed_ticket_ids=failed_ticket_ids,
                        failed_ticket_errors=failed_error_messages,
                    )
                return {
                    **counts,
                    "cursor": completion_cursor,
                    "status": status,
                    "failed_ticket_ids": failed_ticket_ids,
                    "failed_ticket_errors": failed_ticket_errors,
                }
            except Exception as exc:
                failed_ticket_ids = _failed_ticket_ids(failed_ticket_errors)
                failed_error_messages = _failed_ticket_error_messages(failed_ticket_errors)
                async with db_context() as session:
                    await queries.complete_teamwork_update_sync_state(
                        session,
                        cursor=next_cursor,
                        status="error",
                        counts=counts,
                        error=str(exc),
                        failed_ticket_ids=failed_ticket_ids,
                        failed_ticket_errors=failed_error_messages,
                    )
                raise
        finally:
            await release_lock(r, _SYNC_LOCK, lock_token)


async def sync_single_ticket(
    ticket_id: int | str,
    *,
    enqueue_aura_routing_job: Callable[[str], None],
) -> dict:
    """Re-fetch one ticket from Teamwork and run it through the normal sync path.

    Reuses existing content/embedding if the ticket was already processed.
    Does not advance the sync cursor.
    """
    raw_id = int(ticket_id)
    raw = await tw.fetch_ticket_full(raw_id)
    if not raw:
        return {"status": "not_found"}

    counts: dict[str, int] = {
        "processed": 1,
        "imported": 0,
        "updated": 0,
        "protected_skipped": 0,
        "failed": 0,
        "blocked": 0,
        "needs_routing": 0,
    }
    try:
        await _process_changed_ticket(raw, raw_id, counts, enqueue_aura_routing_job)
    except Exception as exc:
        counts["failed"] += 1
        logger.warning("teamwork_sync_single_failed", ticket_id=raw_id, error=str(exc))
    return {"status": "ok" if counts["failed"] == 0 else "error", **counts}
