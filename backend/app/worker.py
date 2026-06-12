"""Celery worker — runs as a separate process alongside the API.

Start worker:
    celery -A app.worker worker --loglevel=info

Start beat scheduler (for cron jobs, runs in a separate process):
    celery -A app.worker beat --loglevel=info

Or combined (dev / single-node):
    celery -A app.worker worker --beat --loglevel=info

Each uploaded PDF and every new Teamwork ticket becomes a queued job that
survives pod restarts.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import NoReturn

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from redis.asyncio import Redis

from app.celery_app import celery_app
from app.config import settings
from app.db import queries
from app.db.connection import close_driver, db_context, init_driver
from app.models.document import DocumentStatusEvent  # noqa: F401 (side-effect import)
from app.services import embeddings as embed_svc
from app.services import llm as llm_svc
from app.services import pdf as pdf_svc
from app.services.aura_routing import route_ticket_with_aura_automated
from app.services.job_status import set_status
from app.services.notifications import push_notification
from app.services.redis_cache import CACHE_KEY_EXPERTS, invalidate_cache
from app.services.redis_lock import refresh_lock, release_lock
from app.services.redis_pubsub import publish_tickets_updated
from app.services.teamwork_import_status import (
    TEAMWORK_IMPORT_LOCK,
    TEAMWORK_IMPORT_LOCK_TTL,
    clear_progress,
    get_progress,
    is_full_import_running,
)
from app.services.teamwork_import_status import (
    set_progress as set_teamwork_import_progress,
)
from app.services.teamwork_sync import (
    run_full_teamwork_import as run_full_teamwork_import_service,
)
from app.services.teamwork_sync import (
    run_teamwork_sync_now,
)

logger = structlog.get_logger()
_IMPORT_LOCK_REFRESH_INTERVAL = 30
_FULL_IMPORT_SOFT_TIME_LIMIT = 6 * 60 * 60
_FULL_IMPORT_TIME_LIMIT = _FULL_IMPORT_SOFT_TIME_LIMIT + (5 * 60)


class TeamworkImportLockLostError(RuntimeError):
    """Raised when a full import worker no longer owns the Redis lock."""


# ---------------------------------------------------------------------------
# Each asyncio.run() call creates a fresh event loop — the Neo4j driver must
# be initialised within the same loop it will be used in.  This context
# manager handles driver init/close around every task's async body.
# verify=False skips the connectivity round-trip; the driver will connect
# lazily on the first query, which is fine for background tasks.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _driver_scope() -> AsyncGenerator[None, None]:
    await init_driver(verify=False)
    try:
        yield
    finally:
        await close_driver()


# ---------------------------------------------------------------------------
# PDF document processing
# ---------------------------------------------------------------------------


@celery_app.task(name="process_document")
def process_document(
    doc_id: str,
    pdf_path: str,
    author_email: str | None,
    tags: list[str],
) -> None:
    async def _run() -> None:
        async with _driver_scope():
            await _process_document(doc_id, pdf_path, author_email, tags)

    asyncio.run(_run())


async def _process_document(
    doc_id: str,
    pdf_path: str,
    author_email: str | None,
    tags: list[str],
) -> None:
    """PDF processing pipeline: OCR → Vision → LLM → Embed → Store."""
    try:
        await set_status(doc_id, "processing", 10, "Extracting text with OCR")
        md_text, images, page_count = await pdf_svc.extract_with_ocr(pdf_path)

        if images:
            await set_status(doc_id, "processing", 25, f"Describing {len(images)} image(s)")
            descriptions = await pdf_svc.describe_images(images)
            md_text = pdf_svc.inject_image_descriptions(md_text, descriptions)

        await set_status(doc_id, "processing", 40, "Extracting metadata")
        metadata = await llm_svc.extract_metadata(md_text)

        await set_status(doc_id, "processing", 55, "Chunking content")
        chunks = pdf_svc.chunk_document(md_text)

        await set_status(doc_id, "processing", 70, f"Embedding {len(chunks)} chunks")
        chunk_embeddings = await embed_svc.generate_embeddings(chunks)

        await set_status(doc_id, "processing", 85, "Storing in database")
        resolved_author = author_email or metadata.get("author")
        all_tags = list(set(tags + metadata.get("topics", [])))
        now = datetime.now(UTC).isoformat()

        async with db_context() as session:
            # Delete stale chunks from any previous processing run before writing new ones
            await session.run(
                "MATCH (d:Document {id: $id})-[:CONTAINS]->(c:Chunk) DETACH DELETE c",
                id=doc_id,
            )
            await session.run(
                """
                MATCH (d:Document {id: $id})
                SET d.title = $title,
                    d.author_email = $author,
                    d.page_count = $pages,
                    d.chunk_count = $chunks,
                    d.status = 'processing',
                    d.processed_at = $now
                """,
                id=doc_id,
                title=metadata.get("title", "Untitled"),
                author=resolved_author,
                pages=page_count,
                chunks=len(chunks),
                now=now,
            )

            chunk_data = [
                {
                    "chunk_id": f"{doc_id}_{idx}",
                    "idx": idx,
                    "content": text,
                    "embedding": embedding,
                    "tokens": len(text.split()),
                }
                for idx, (text, embedding) in enumerate(zip(chunks, chunk_embeddings, strict=True))
            ]
            batch_size = 50
            for i in range(0, len(chunk_data), batch_size):
                batch = chunk_data[i : i + batch_size]
                await session.run(
                    """
                    UNWIND $chunks AS c
                    CREATE (ch:Chunk {
                        id: c.chunk_id,
                        document_id: $doc_id,
                        page_number: 0,
                        chunk_index: c.idx,
                        content: c.content,
                        embedding: c.embedding,
                        token_count: c.tokens
                    })
                    WITH ch, c
                    MATCH (d:Document {id: $doc_id})
                    CREATE (d)-[:CONTAINS]->(ch)
                    """,
                    chunks=batch,
                    doc_id=doc_id,
                )

            # Link topics via TAGGED — batch all tags in one round-trip
            tags = [tag.lower().strip() for tag in all_tags if tag.strip()]
            if tags:
                await session.run(
                    """
                    UNWIND $tags AS tag
                    MERGE (t:Topic {name: tag})
                    WITH t
                    MATCH (d:Document {id: $id})
                    MERGE (d)-[:TAGGED]->(t)
                    """,
                    tags=tags,
                    id=doc_id,
                )

            if resolved_author:
                await session.run(
                    """
                    MATCH (u:User {email: $email}), (d:Document {id: $id})
                    MERGE (u)-[:AUTHORED {authored_at: $now}]->(d)
                    """,
                    email=resolved_author,
                    id=doc_id,
                    now=now,
                )

            await session.run(
                "MATCH (d:Document {id: $id}) SET d.status = 'completed'",
                id=doc_id,
            )

        await set_status(doc_id, "completed", 100, "Document processed successfully")
        logger.info("Document processed", doc_id=doc_id, chunks=len(chunks), pages=page_count)
        title = metadata.get("title") or "Untitled"
        await push_notification(
            type="document",
            message=f'"{title}" processed — {len(chunks)} chunks, {page_count} pages',
            status="success",
        )

    except Exception as exc:
        logger.error("Processing failed", doc_id=doc_id, error=str(exc))
        async with db_context() as session:
            await session.run(
                "MATCH (d:Document {id: $id}) SET d.status = 'failed', d.error_message = $msg",
                id=doc_id,
                msg=str(exc),
            )
        await set_status(doc_id, "failed", 0, str(exc))
        await push_notification(
            type="document",
            message=f"Document processing failed: {exc}",
            status="error",
        )


# ---------------------------------------------------------------------------
# Aura ticket routing — serial via Redis lock
# ---------------------------------------------------------------------------

_AURA_ROUTING_LOCK = "korca:aura_routing_lock"
_AURA_RATE_SLOT_KEY = "korca:aura_routing_rate_slot"
_AURA_COOLDOWN_KEY = "korca:aura_routing_cooldown"
_AURA_MIN_START_INTERVAL_SECONDS = 60
_AURA_RATE_LIMIT_COOLDOWN_SECONDS = 10 * 60
_AURA_TRANSIENT_RETRY_SECONDS = 60
_AURA_MAX_RETRIES = 6
_AURA_LOCK_TTL = 180  # auto-expires if worker crashes mid-job
_AURA_LOCK_POLL = 3  # seconds between retries while waiting
_AURA_LOCK_TIMEOUT = 120  # must stay well below task_soft_time_limit (570s) so the retry path fires before Celery kills the task
_AURA_STALE_RUNNING_MINUTES = 3
_AURA_COOLDOWN_MESSAGE = "Aura is rate-limiting routing requests; retrying after cooldown."


class _AuraRoutingRetry(Exception):
    def __init__(self, message: str, countdown: int):
        super().__init__(message)
        self.countdown = countdown


def _aura_retry_countdown(exc: Exception) -> int | None:
    message = str(exc)
    if "429" in message or "Too Many Requests" in message:
        return _AURA_RATE_LIMIT_COOLDOWN_SECONDS
    if "502" in message or "503" in message:
        return _AURA_TRANSIENT_RETRY_SECONDS
    return None


async def _mark_aura_routing_retry(ticket_id: str, error: str) -> None:
    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(
            session,
            ticket_id=ticket_id,
            status="queued",
            error=error,
        )


async def _mark_aura_routing_failed(ticket_id: str, error: str) -> None:
    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(
            session,
            ticket_id=ticket_id,
            status="failed",
            error=error,
        )


def _aura_retries_exhausted(task: object) -> bool:
    request = getattr(task, "request", None)
    retries = getattr(request, "retries", 0) or 0
    max_retries = getattr(task, "max_retries", _AURA_MAX_RETRIES)
    return max_retries is not None and retries >= max_retries


async def _mark_aura_routing_failed_with_driver(ticket_id: str, error: str) -> None:
    async with _driver_scope():
        await _mark_aura_routing_failed(ticket_id, error)


def _fail_aura_routing_after_retry_exhaustion(ticket_id: str, error: str) -> None:
    message = f"Aura routing retries exhausted: {error}"
    asyncio.run(_mark_aura_routing_failed_with_driver(ticket_id, message))
    raise RuntimeError(message)


async def _set_aura_cooldown(r: Redis) -> None:
    await r.set(_AURA_COOLDOWN_KEY, "1", ex=_AURA_RATE_LIMIT_COOLDOWN_SECONDS)


async def _defer_if_aura_cooldown_active(r: Redis, ticket_id: str) -> None:
    ttl_ms = await r.pttl(_AURA_COOLDOWN_KEY)
    if ttl_ms <= 0:
        return
    countdown = max(1, (ttl_ms + 999) // 1000 + 1)
    await _mark_aura_routing_retry(ticket_id, _AURA_COOLDOWN_MESSAGE)
    raise _AuraRoutingRetry(_AURA_COOLDOWN_MESSAGE, countdown)


async def _wait_for_aura_rate_slot(r: Redis, ticket_id: str) -> None:
    while True:
        acquired = await r.set(
            _AURA_RATE_SLOT_KEY,
            ticket_id,
            nx=True,
            ex=_AURA_MIN_START_INTERVAL_SECONDS,
        )
        if acquired:
            return

        ttl_ms = await r.pttl(_AURA_RATE_SLOT_KEY)
        wait_seconds = max(1.0, ttl_ms / 1000 if ttl_ms > 0 else 1.0)
        logger.info(
            "aura_routing_rate_limited",
            ticket_id=ticket_id,
            wait_seconds=round(wait_seconds, 2),
        )
        await asyncio.sleep(wait_seconds)


async def _handle_aura_routing_failure(r: Redis, ticket_id: str, exc: Exception) -> NoReturn:
    """Classify a routing failure: retry on rate-limit/transient, else mark failed and re-raise.

    FastAPI HTTPException can't be pickled by Celery, so it is converted to a RuntimeError.
    """
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        msg = f"Aura routing failed [{exc.status_code}]: {exc.detail}"
        countdown = _aura_retry_countdown(RuntimeError(msg))
        if countdown is None:
            raise RuntimeError(msg) from exc
        if countdown == _AURA_RATE_LIMIT_COOLDOWN_SECONDS:
            await _set_aura_cooldown(r)
        await _mark_aura_routing_retry(ticket_id, msg)
        raise _AuraRoutingRetry(msg, countdown) from exc

    countdown = _aura_retry_countdown(exc)
    if countdown is not None:
        if countdown == _AURA_RATE_LIMIT_COOLDOWN_SECONDS:
            await _set_aura_cooldown(r)
        message = (
            _AURA_COOLDOWN_MESSAGE
            if countdown == _AURA_RATE_LIMIT_COOLDOWN_SECONDS
            else "Transient Aura routing error; retrying."
        )
        await _mark_aura_routing_retry(ticket_id, message)
        raise _AuraRoutingRetry(str(exc), countdown) from exc

    async with db_context() as session:
        await queries.set_ticket_aura_routing_status(
            session,
            ticket_id=ticket_id,
            status="failed",
            error=str(exc),
        )
    raise exc


@celery_app.task(
    name="process_aura_routing_ticket",
    bind=True,
    max_retries=_AURA_MAX_RETRIES,
    default_retry_delay=60,
)
def process_aura_routing_ticket(self, ticket_id: str) -> dict:
    async def _run() -> dict:
        async with _driver_scope():
            return await _process_aura_routing_ticket(ticket_id)

    try:
        return asyncio.run(_run())
    except _AuraRoutingRetry as exc:
        if _aura_retries_exhausted(self):
            _fail_aura_routing_after_retry_exhaustion(ticket_id, str(exc))
        raise self.retry(exc=exc, countdown=exc.countdown) from exc
    except SoftTimeLimitExceeded:
        # Celery kills the task from outside; without this the ticket stays
        # "queued" forever with no live job behind it.
        asyncio.run(
            _mark_aura_routing_failed_with_driver(
                ticket_id, "Aura routing job timed out; use Reroute to retry."
            )
        )
        raise
    except RuntimeError as exc:
        # Retry transient Aura failures (502/503); propagate permanent ones (404)
        if "502" in str(exc) or "503" in str(exc):
            if _aura_retries_exhausted(self):
                _fail_aura_routing_after_retry_exhaustion(ticket_id, str(exc))
            raise self.retry(exc=exc) from exc
        raise


async def _process_aura_routing_ticket(ticket_id: str) -> dict:
    """Route one ticket through Aura. Only one call runs at a time via Redis lock."""
    # Guard: skip if already routed — makes retries and duplicate enqueues idempotent
    async with db_context() as session:
        if await queries.has_routing_recommendation(session, ticket_id):
            logger.info("aura_routing_skipped_already_routed", ticket_id=ticket_id)
            return {"skipped": True, "reason": "already_routed"}

    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        deadline = asyncio.get_event_loop().time() + _AURA_LOCK_TIMEOUT
        while True:
            acquired = await r.set(_AURA_ROUTING_LOCK, ticket_id, nx=True, ex=_AURA_LOCK_TTL)
            if acquired:
                break
            if asyncio.get_event_loop().time() > deadline:
                message = f"Aura routing lock timeout for ticket {ticket_id}; retrying."
                await _mark_aura_routing_retry(ticket_id, message)
                raise _AuraRoutingRetry(message, _AURA_TRANSIENT_RETRY_SECONDS)
            await asyncio.sleep(_AURA_LOCK_POLL)

        try:
            await _defer_if_aura_cooldown_active(r, ticket_id)
            await _wait_for_aura_rate_slot(r, ticket_id)
            await r.expire(_AURA_ROUTING_LOCK, _AURA_LOCK_TTL)
            logger.info("aura_routing_job_started", ticket_id=ticket_id)
            try:
                result = await route_ticket_with_aura_automated(str(ticket_id))
            except Exception as exc:
                await _handle_aura_routing_failure(r, ticket_id, exc)
            logger.info(
                "aura_routing_job_finished",
                ticket_id=ticket_id,
                expert_email=result.get("expert_email"),
            )
            return result
        finally:
            await r.delete(_AURA_ROUTING_LOCK)


async def _recover_stale_aura_routing_jobs() -> list[str]:
    """Requeue Aura jobs interrupted after marking a ticket as running."""
    async with db_context() as session:
        ticket_ids = await queries.list_stale_aura_routing_tickets(
            session,
            stale_minutes=_AURA_STALE_RUNNING_MINUTES,
            limit=20,
        )

    for ticket_id in ticket_ids:
        async with db_context() as session:
            await queries.set_ticket_aura_routing_status(
                session,
                ticket_id=ticket_id,
                status="queued",
                error="Previous Aura routing job was interrupted; retrying.",
            )
        process_aura_routing_ticket.delay(str(ticket_id))
        logger.warning("aura_routing_requeued_stale_running_ticket", ticket_id=ticket_id)

    return ticket_ids


# ---------------------------------------------------------------------------
# Teamwork auto-sync cron (runs every minute, self-throttles via DB state)
# ---------------------------------------------------------------------------


@celery_app.task(name="generate_teamwork_expert_skill_clouds")
def generate_teamwork_expert_skill_clouds() -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with _driver_scope():
            return await _generate_teamwork_expert_skill_clouds()

    return asyncio.run(_run())


async def _generate_teamwork_expert_skill_clouds() -> dict[str, int]:
    counts = {"experts_seen": 0, "generated": 0, "skipped": 0, "failed": 0}
    async with db_context() as session:
        experts = await queries.list_teamwork_experts_for_skill_generation(session)

    counts["experts_seen"] = len(experts)
    for expert in experts:
        user_id = expert.get("id")
        if not user_id:
            counts["skipped"] += 1
            continue
        try:
            async with db_context() as session:
                summaries = await queries.get_expert_ticket_summaries(session, user_id)
            if not summaries:
                counts["skipped"] += 1
                continue

            skills = await llm_svc.generate_expert_skills(
                expert.get("name") or expert.get("email") or user_id,
                summaries,
            )
            skills = [s.strip() for s in skills if s and s.strip()]
            if not skills:
                counts["skipped"] += 1
                continue

            embeddings = await embed_svc.generate_embeddings(skills)
            skill_embeddings = {s.lower(): emb for s, emb in zip(skills, embeddings, strict=True)}
            async with db_context() as session:
                await queries.update_user_profile(
                    session,
                    user_id,
                    department=None,
                    title=None,
                    manager_email=None,
                    skills=skills,
                    skill_embeddings=skill_embeddings,
                )
            counts["generated"] += 1
        except Exception as exc:
            counts["failed"] += 1
            logger.warning(
                "teamwork_skill_generation_failed",
                user_id=user_id,
                email=expert.get("email"),
                error=str(exc),
            )

    logger.info("teamwork_skill_generation_finished", **counts)
    if counts["generated"] > 0:
        await invalidate_cache(CACHE_KEY_EXPERTS)
    # Clear the import progress status in Redis if it's still completed (not overwritten by a new import)
    progress = await get_progress()
    if progress and progress.status == "completed":
        await clear_progress()
    return counts


@celery_app.task(
    name="run_full_teamwork_import",
    soft_time_limit=_FULL_IMPORT_SOFT_TIME_LIMIT,
    time_limit=_FULL_IMPORT_TIME_LIMIT,
)
def run_full_teamwork_import(lock_token: str) -> dict:
    async def _run() -> dict:
        async with _driver_scope():
            return await _run_full_teamwork_import(lock_token)

    return asyncio.run(_run())


async def _teamwork_import_lock_heartbeat(lock_token: str, stop_event: asyncio.Event) -> None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_IMPORT_LOCK_REFRESH_INTERVAL)
                return
            except TimeoutError:
                pass

            refreshed = await refresh_lock(
                r, TEAMWORK_IMPORT_LOCK, lock_token, TEAMWORK_IMPORT_LOCK_TTL
            )
            if not refreshed:
                raise TeamworkImportLockLostError("Lost Teamwork import lock")


def _queue_initial_skill_generation_and_completion_message(result: dict) -> str:
    initial_import = result.get("initial_import", result.get("created_after") is None)
    if initial_import and result.get("imported", 0) > 0:
        try:
            generate_teamwork_expert_skill_clouds.delay()
            return "Import finished; skill generation queued."
        except Exception as exc:
            logger.warning("teamwork_skill_generation_enqueue_failed", error=str(exc))
            return "Import finished; skill generation could not be queued."
    return "Import finished."


async def _run_full_teamwork_import(lock_token: str) -> dict:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        owns_lock = await refresh_lock(
            r, TEAMWORK_IMPORT_LOCK, lock_token, TEAMWORK_IMPORT_LOCK_TTL
        )
        if not owns_lock:
            logger.warning("teamwork_full_import_skipped_lock_not_owned")
            return {"skipped": True, "reason": "lock_not_owned"}

        stop_event = asyncio.Event()
        heartbeat = asyncio.create_task(_teamwork_import_lock_heartbeat(lock_token, stop_event))
        try:
            import_task = asyncio.create_task(
                run_full_teamwork_import_service(set_progress=set_teamwork_import_progress)
            )
            done, _pending = await asyncio.wait(
                {import_task, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                heartbeat_error = heartbeat.exception()
                if heartbeat_error:
                    import_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await import_task
                    raise heartbeat_error

            result = await import_task
            message = _queue_initial_skill_generation_and_completion_message(result)
            total = int(result.get("total") or 0)
            await set_teamwork_import_progress(
                status="completed",
                message=message,
                processed=total,
                imported=int(result.get("imported") or 0),
                skipped=int(result.get("skipped") or 0),
                failed=int(result.get("failed") or 0),
                total=total,
                finished_at=datetime.now(UTC).isoformat(),
            )
            logger.info("teamwork_full_import_finished", **result)
            return result
        except TeamworkImportLockLostError:
            logger.warning("teamwork_full_import_lost_lock")
            raise
        except Exception as exc:
            message = f"Teamwork import failed: {exc}"
            await set_teamwork_import_progress(
                status="error",
                message=message,
                finished_at=datetime.now(UTC).isoformat(),
                error=message,
            )
            logger.error("teamwork_full_import_failed", error=str(exc))
            raise
        finally:
            stop_event.set()
            if not heartbeat.done():
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            await release_lock(r, TEAMWORK_IMPORT_LOCK, lock_token)


@celery_app.task(name="poll_teamwork_updates")
def poll_teamwork_updates() -> None:
    async def _run() -> None:
        async with _driver_scope():
            await _poll_teamwork_updates()

    asyncio.run(_run())


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def _poll_teamwork_updates() -> None:
    """Recover stale Aura routing jobs and run auto-sync when enabled."""
    await _recover_stale_aura_routing_jobs()

    if await is_full_import_running():
        logger.info("teamwork_auto_sync_skipped_full_import_running")
        return

    async with db_context() as session:
        settings_row = await queries.get_teamwork_auto_sync_settings(session)
        state = await queries.get_teamwork_update_sync_state(session)

    if not settings_row["enabled"] or not state or not state.get("cursor"):
        return

    interval_seconds = int(settings_row["interval_seconds"])
    last_run = _parse_iso(state.get("last_run_at"))
    if last_run:
        elapsed = (datetime.now(UTC) - last_run).total_seconds()
        if elapsed < interval_seconds:
            return

    logger.info("teamwork_auto_sync_started", interval_seconds=interval_seconds)
    result = await run_teamwork_sync_now(enqueue_aura_routing_job=process_aura_routing_ticket.delay)
    changed = result.get("updated", 0) + result.get("imported", 0)
    if changed > 0:
        await publish_tickets_updated(changed)
