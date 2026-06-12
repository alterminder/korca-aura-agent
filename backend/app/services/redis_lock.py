"""Small Redis lock helpers with owner-token release."""

from __future__ import annotations

from uuid import uuid4

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_REFRESH_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], tonumber(ARGV[2]))
end
return 0
"""


async def acquire_lock(redis, key: str, ttl_seconds: int) -> str | None:
    token = uuid4().hex
    acquired = await redis.set(key, token, nx=True, ex=ttl_seconds)
    return token if acquired else None


async def release_lock(redis, key: str, token: str) -> bool:
    return bool(await redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token))


async def refresh_lock(redis, key: str, token: str, ttl_seconds: int) -> bool:
    return bool(await redis.eval(_REFRESH_LOCK_SCRIPT, 1, key, token, ttl_seconds))
