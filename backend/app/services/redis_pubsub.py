"""Redis pub/sub helpers for server-sent event push notifications."""

import json

from redis.asyncio import Redis

from app.config import settings

TICKETS_CHANNEL = "korca:events:tickets"


async def publish_tickets_updated(count: int) -> None:
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            await r.publish(
                TICKETS_CHANNEL, json.dumps({"event": "tickets_updated", "count": count})
            )
    except Exception:
        pass
