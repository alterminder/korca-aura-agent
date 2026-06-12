import asyncio

import pytest

from app.services.redis_lock import refresh_lock


class _FakeRedis:
    def __init__(self, current_token: str | None):
        self.current_token = current_token
        self.eval_calls = []

    async def eval(self, script, numkeys, key, token, ttl):
        await asyncio.sleep(0)
        self.eval_calls.append((script, numkeys, key, token, ttl))
        if self.current_token == token:
            return 1
        return 0


@pytest.mark.asyncio
async def test_refresh_lock_extends_only_matching_owner_token():
    redis = _FakeRedis("owner-token")

    refreshed = await refresh_lock(redis, "import-lock", "owner-token", 120)

    assert refreshed is True
    assert redis.eval_calls == [
        (
            redis.eval_calls[0][0],
            1,
            "import-lock",
            "owner-token",
            120,
        )
    ]


@pytest.mark.asyncio
async def test_refresh_lock_rejects_stale_owner_token():
    redis = _FakeRedis("new-owner-token")

    refreshed = await refresh_lock(redis, "import-lock", "old-owner-token", 120)

    assert refreshed is False
