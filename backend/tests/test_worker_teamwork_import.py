import asyncio

import pytest

from app import worker
from app.services.teamwork_import_status import TEAMWORK_IMPORT_LOCK, TEAMWORK_IMPORT_LOCK_TTL


def test_full_import_task_uses_extended_time_limit():
    assert worker.run_full_teamwork_import.soft_time_limit == 6 * 60 * 60
    assert worker.run_full_teamwork_import.time_limit == (6 * 60 * 60) + (5 * 60)


def test_full_import_completion_queues_skills_for_initial_import_continuation(monkeypatch):
    events = []

    class _FakeSkillTask:
        def delay(self):
            events.append("skill")

    monkeypatch.setattr("app.worker.generate_teamwork_expert_skill_clouds", _FakeSkillTask())

    message = worker._queue_initial_skill_generation_and_completion_message(
        {
            "initial_import": True,
            "created_after": "2026-06-06T18:55:00Z",
            "imported": 1,
        }
    )

    assert events == ["skill"]
    assert message == "Import finished; skill generation queued."


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
    def __init__(self, refresh_ok: bool):
        self.refresh_ok = refresh_ok
        self.eval_calls = []

    async def eval(self, script, numkeys, key, token, *args):
        await _async_value(None)
        self.eval_calls.append((script, numkeys, key, token, args))
        if len(args) == 1:
            return 1 if self.refresh_ok else 0
        return 1


@pytest.mark.asyncio
async def test_full_import_worker_exits_without_import_when_lock_token_expired(monkeypatch):
    import_calls = []

    async def fake_import(*, set_progress):
        await _async_value(None)
        import_calls.append(set_progress)
        return {"created_after": None, "imported": 0, "skipped": 0, "failed": 0, "total": 0}

    monkeypatch.setattr(
        "app.worker.Redis.from_url",
        lambda *_args, **_kwargs: _RedisContext(_FakeRedis(refresh_ok=False)),
    )
    monkeypatch.setattr("app.worker.run_full_teamwork_import_service", fake_import)

    result = await worker._run_full_teamwork_import("stale-token")

    assert result == {"skipped": True, "reason": "lock_not_owned"}
    assert import_calls == []


@pytest.mark.asyncio
async def test_full_import_worker_writes_completed_before_releasing_lock(monkeypatch):
    events = []

    async def fake_import(*, set_progress):
        await _async_value(None)
        events.append("import")
        return {"created_after": None, "imported": 1, "skipped": 2, "failed": 0, "total": 3}

    async def fake_progress(**kwargs):
        await _async_value(None)
        events.append(f"progress:{kwargs['status']}")

    async def fake_refresh(redis, key, token, ttl):
        await _async_value(None)
        assert key == TEAMWORK_IMPORT_LOCK
        assert ttl == TEAMWORK_IMPORT_LOCK_TTL
        return True

    async def fake_release(redis, key, token):
        await _async_value(None)
        events.append("release")
        return True

    async def fake_heartbeat(_lock_token, stop_event):
        await stop_event.wait()

    class _FakeSkillTask:
        def delay(self):
            events.append("skill")

    monkeypatch.setattr(
        "app.worker.Redis.from_url",
        lambda *_args, **_kwargs: _RedisContext(_FakeRedis(refresh_ok=True)),
    )
    monkeypatch.setattr("app.worker.run_full_teamwork_import_service", fake_import)
    monkeypatch.setattr("app.worker.set_teamwork_import_progress", fake_progress)
    monkeypatch.setattr("app.worker.refresh_lock", fake_refresh)
    monkeypatch.setattr("app.worker.release_lock", fake_release)
    monkeypatch.setattr("app.worker._teamwork_import_lock_heartbeat", fake_heartbeat)
    monkeypatch.setattr("app.worker.generate_teamwork_expert_skill_clouds", _FakeSkillTask())

    result = await worker._run_full_teamwork_import("owner-token")

    assert result["imported"] == 1
    assert events == ["import", "skill", "progress:completed", "release"]


@pytest.mark.asyncio
async def test_full_import_worker_does_not_overwrite_progress_after_lock_loss(monkeypatch):
    events = []
    never_finish = asyncio.Event()

    async def fake_import(*, set_progress):
        await never_finish.wait()

    async def fake_progress(**kwargs):
        await _async_value(None)
        events.append(f"progress:{kwargs['status']}")

    async def fake_refresh(redis, key, token, ttl):
        return await _async_value(True)

    async def fake_release(redis, key, token):
        await _async_value(None)
        events.append("release")
        return True

    async def fake_heartbeat(_lock_token, _stop_event):
        await _async_value(None)
        raise worker.TeamworkImportLockLostError("Lost Teamwork import lock")

    monkeypatch.setattr(
        "app.worker.Redis.from_url",
        lambda *_args, **_kwargs: _RedisContext(_FakeRedis(refresh_ok=True)),
    )
    monkeypatch.setattr("app.worker.run_full_teamwork_import_service", fake_import)
    monkeypatch.setattr("app.worker.set_teamwork_import_progress", fake_progress)
    monkeypatch.setattr("app.worker.refresh_lock", fake_refresh)
    monkeypatch.setattr("app.worker.release_lock", fake_release)
    monkeypatch.setattr("app.worker._teamwork_import_lock_heartbeat", fake_heartbeat)

    with pytest.raises(RuntimeError, match="Lost Teamwork import lock"):
        await worker._run_full_teamwork_import("owner-token")

    assert events == ["release"]
