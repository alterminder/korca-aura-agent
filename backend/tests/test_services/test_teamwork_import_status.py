import asyncio
import json

import pytest

from app.services import teamwork_import_status as status_store


async def _async_value(value):
    await asyncio.sleep(0)
    return value


class _RedisContext:
    def __init__(self, redis):
        self._redis = redis

    async def __aenter__(self):
        return await _async_value(self._redis)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.set_calls = []
        self.exists_keys: set[str] = set()

    async def get(self, key):
        return await _async_value(self.values.get(key))

    async def set(self, key, value, *, ex):
        await _async_value(None)
        self.values[key] = value
        self.set_calls.append((key, json.loads(value), ex))

    async def delete(self, key):
        await _async_value(None)
        self.values.pop(key, None)

    async def exists(self, key):
        return await _async_value(1 if key in self.exists_keys else 0)


@pytest.mark.asyncio
async def test_effective_import_progress_marks_stale_running_progress_interrupted(monkeypatch):
    redis = _FakeRedis()
    redis.values[status_store.TEAMWORK_IMPORT_PROGRESS_KEY] = json.dumps(
        {
            "status": "running",
            "message": "Processed 10/100",
            "processed": 10,
            "imported": 8,
            "skipped": 1,
            "failed": 1,
            "total": 100,
            "started_at": "2026-06-07T10:00:00Z",
            "updated_at": "2026-06-07T10:01:00Z",
        }
    )
    monkeypatch.setattr(
        "app.services.teamwork_import_status.Redis.from_url",
        lambda *_args, **_kwargs: _RedisContext(redis),
    )

    progress, import_running = await status_store.get_effective_import_progress()

    assert import_running is False
    assert progress.status == "error"
    assert progress.message == "Import interrupted before completion. Start a new import to continue."
    assert progress.error == progress.message
    assert redis.set_calls[-1][1]["status"] == "error"


@pytest.mark.asyncio
async def test_effective_import_progress_returns_idle_when_no_progress_or_lock(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(
        "app.services.teamwork_import_status.Redis.from_url",
        lambda *_args, **_kwargs: _RedisContext(redis),
    )

    progress, import_running = await status_store.get_effective_import_progress()

    assert import_running is False
    assert progress.status == "idle"
    assert progress.message == "No Teamwork import has run yet."
