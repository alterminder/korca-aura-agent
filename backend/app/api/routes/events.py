from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.services.notifications import NOTIFICATIONS_CHANNEL
from app.services.redis_pubsub import TICKETS_CHANNEL

router = APIRouter()


@router.get("/tickets")
async def ticket_update_events(request: Request) -> EventSourceResponse:
    """SSE stream that pushes a tickets_updated event whenever auto-sync finds changes."""

    async def generator():
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            pubsub = r.pubsub()
            await pubsub.subscribe(TICKETS_CHANNEL)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message["type"] == "message":
                        yield {"data": message["data"]}
            finally:
                await pubsub.unsubscribe(TICKETS_CHANNEL)
                await pubsub.aclose()

    return EventSourceResponse(generator(), ping=30)


@router.get("/notifications")
async def notification_events(request: Request) -> EventSourceResponse:
    """SSE stream that pushes notification events in real-time."""

    async def generator():
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            pubsub = r.pubsub()
            await pubsub.subscribe(NOTIFICATIONS_CHANNEL)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message["type"] == "message":
                        yield {"data": message["data"]}
            finally:
                await pubsub.unsubscribe(NOTIFICATIONS_CHANNEL)
                await pubsub.aclose()

    return EventSourceResponse(generator(), ping=30)
