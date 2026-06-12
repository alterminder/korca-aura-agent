"""Redis-backed document processing status store.

Replaces the in-memory _status dict in documents.py so that both the API
pod and the Celery worker pod share the same status view.
"""

import json

from redis.asyncio import Redis

from app.config import settings
from app.models.document import DocumentStatusEvent

_PREFIX = "korca:docstatus:"
_TTL = 3600  # 1 hour — long enough for any reasonable upload + SSE poll


def _key(doc_id: str) -> str:
    return f"{_PREFIX}{doc_id}"


async def set_status(doc_id: str, status: str, progress: int, message: str | None = None) -> None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        data = json.dumps(
            {"id": doc_id, "status": status, "progress": progress, "message": message}
        )
        await r.set(_key(doc_id), data, ex=_TTL)


async def get_status(doc_id: str) -> DocumentStatusEvent | None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        raw = await r.get(_key(doc_id))
    if not raw:
        return None
    data = json.loads(raw)
    return DocumentStatusEvent(**data)


async def delete_status(doc_id: str) -> None:
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        await r.delete(_key(doc_id))
