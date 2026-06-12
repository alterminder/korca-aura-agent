"""Notification persistence and pub/sub helpers."""

import json
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.config import settings

NOTIFICATIONS_LIST = "korca:notifications"
NOTIFICATIONS_CHANNEL = "korca:events:notifications"
MAX_NOTIFICATIONS = 100


async def push_notification(type: str, message: str, status: str = "info") -> None:
    payload = json.dumps(
        {
            "type": type,
            "message": message,
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            await r.lpush(NOTIFICATIONS_LIST, payload)
            await r.ltrim(NOTIFICATIONS_LIST, 0, MAX_NOTIFICATIONS - 1)
            await r.publish(NOTIFICATIONS_CHANNEL, payload)
    except Exception:
        pass


async def get_notifications(limit: int = 20) -> list[dict]:
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            items = await r.lrange(NOTIFICATIONS_LIST, 0, limit - 1)
        return [json.loads(item) for item in items]
    except Exception:
        return []
