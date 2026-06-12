"""Redis-backed progress and liveness helpers for the full Teamwork import."""

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from redis.asyncio import Redis

from app.config import settings

TEAMWORK_IMPORT_LOCK = "korca:teamwork_import_lock"
TEAMWORK_IMPORT_LOCK_TTL = 120
TEAMWORK_IMPORT_PROGRESS_KEY = "korca:teamwork_import:progress"
TEAMWORK_IMPORT_PROGRESS_TTL = 7200

ACTIVE_IMPORT_STATUSES = frozenset({"queued", "running"})
TERMINAL_IMPORT_STATUSES = frozenset({"completed", "error", "idle"})
INTERRUPTED_IMPORT_MESSAGE = "Import interrupted before completion. Start a new import to continue."
IDLE_IMPORT_MESSAGE = "No Teamwork import has run yet."

ImportProgressStatus = Literal["idle", "queued", "running", "completed", "error"]


class TeamworkImportProgress(BaseModel):
    status: ImportProgressStatus
    message: str
    processed: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    total: int | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def idle_progress() -> TeamworkImportProgress:
    now = _now()
    return TeamworkImportProgress(
        status="idle",
        message=IDLE_IMPORT_MESSAGE,
        updated_at=now,
        finished_at=now,
    )


async def _write_progress(redis: Redis, progress: TeamworkImportProgress) -> None:
    await redis.set(
        TEAMWORK_IMPORT_PROGRESS_KEY,
        progress.model_dump_json(exclude_none=True),
        ex=TEAMWORK_IMPORT_PROGRESS_TTL,
    )


async def _read_progress(redis: Redis) -> TeamworkImportProgress | None:
    raw = await redis.get(TEAMWORK_IMPORT_PROGRESS_KEY)
    if not raw:
        return None
    data = json.loads(raw)
    return TeamworkImportProgress.model_validate(data)


async def set_progress(
    *,
    status: ImportProgressStatus,
    message: str,
    processed: int = 0,
    imported: int = 0,
    skipped: int = 0,
    failed: int = 0,
    total: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str | None = None,
) -> TeamworkImportProgress:
    now = _now()
    progress = TeamworkImportProgress(
        status=status,
        message=message,
        processed=processed,
        imported=imported,
        skipped=skipped,
        failed=failed,
        total=total,
        started_at=started_at,
        updated_at=now,
        finished_at=finished_at,
        error=error,
    )
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        await _write_progress(redis, progress)
    return progress


async def get_progress() -> TeamworkImportProgress | None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        return await _read_progress(redis)


async def clear_progress() -> None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        await redis.delete(TEAMWORK_IMPORT_PROGRESS_KEY)


async def _resolve_effective_import_progress(
    redis: Redis,
) -> tuple[TeamworkImportProgress, bool]:
    progress = await _read_progress(redis)
    lock_exists = bool(await redis.exists(TEAMWORK_IMPORT_LOCK))

    if progress is None:
        if lock_exists:
            return (
                TeamworkImportProgress(
                    status="queued",
                    message="Import starting...",
                    updated_at=_now(),
                ),
                True,
            )
        return idle_progress(), False

    import_running = lock_exists and progress.status in ACTIVE_IMPORT_STATUSES
    if progress.status in ACTIVE_IMPORT_STATUSES and not lock_exists:
        now = _now()
        interrupted = progress.model_copy(
            update={
                "status": "error",
                "message": INTERRUPTED_IMPORT_MESSAGE,
                "updated_at": now,
                "finished_at": now,
                "error": INTERRUPTED_IMPORT_MESSAGE,
            }
        )
        await _write_progress(redis, interrupted)
        return interrupted, False

    return progress, import_running


async def get_effective_import_progress(
    redis: Redis | None = None,
) -> tuple[TeamworkImportProgress, bool]:
    if redis is not None:
        return await _resolve_effective_import_progress(redis)
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis_client:
        return await _resolve_effective_import_progress(redis_client)


async def is_full_import_running() -> bool:
    _progress, import_running = await get_effective_import_progress()
    return import_running
