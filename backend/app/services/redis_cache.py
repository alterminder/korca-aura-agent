"""Redis cache helper for expensive database queries."""

from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis

from app.config import settings

logger = structlog.get_logger()

CACHE_KEY_EXPERTS = "korca:cache:experts"
CACHE_KEY_FILTERS = "korca:cache:filter_options"
DEFAULT_TTL = 3600  # 1 hour


async def get_cached_data(key: str) -> list | dict | None:
    """Fetch parsed JSON data from cache."""
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            val = await r.get(key)
            if val:
                logger.debug("cache_hit", key=key)
                return json.loads(val)
    except Exception as exc:
        logger.warning("cache_read_error", key=key, error=str(exc))
    return None


async def set_cached_data(key: str, data: list | dict, ttl: int = DEFAULT_TTL) -> None:
    """Store serialized JSON data in cache with a TTL."""
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            await r.set(key, json.dumps(data, default=str), ex=ttl)
            logger.debug("cache_write", key=key, ttl=ttl)
    except Exception as exc:
        logger.warning("cache_write_error", key=key, error=str(exc))


async def invalidate_cache(*keys: str) -> None:
    """Delete keys from cache to force reload."""
    try:
        async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
            for key in keys:
                await r.delete(key)
            logger.info("cache_invalidated", keys=keys)
    except Exception as exc:
        logger.warning("cache_invalidation_error", keys=keys, error=str(exc))
