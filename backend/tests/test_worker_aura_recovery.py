import asyncio

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app import worker


async def _async_value(value):
    await asyncio.sleep(0)
    return value


class _FakeRedis:
    def __init__(self):
        self.set_calls = []
        self.pttl_calls = []

    async def set(self, *args, **kwargs):
        await asyncio.sleep(0)
        self.set_calls.append((args, kwargs))
        return True

    async def pttl(self, key):
        await asyncio.sleep(0)
        self.pttl_calls.append(key)
        return -2


class _FakeDbContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return await _async_value(self._session)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


class _NullDriverScope:
    async def __aenter__(self):
        return await _async_value(None)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


class _RedisContext:
    def __init__(self, redis):
        self._redis = redis

    async def __aenter__(self):
        return await _async_value(self._redis)

    async def __aexit__(self, exc_type, exc, tb):
        return await _async_value(False)


@pytest.mark.asyncio
async def test_recover_stale_aura_routing_jobs_requeues_orphaned_running_tickets(monkeypatch):
    session = object()
    status_updates = []
    enqueued = []

    async def fake_list_stale(_session, *, stale_minutes, limit):
        await _async_value(None)
        assert _session is session
        assert stale_minutes == 3
        assert limit == 20
        return ["4099107"]

    async def fake_set_status(_session, **kwargs):
        await asyncio.sleep(0)
        status_updates.append(kwargs)

    class _FakeTask:
        def delay(self, ticket_id):
            enqueued.append(ticket_id)

    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.worker.queries.list_stale_aura_routing_tickets", fake_list_stale)
    monkeypatch.setattr("app.worker.queries.set_ticket_aura_routing_status", fake_set_status)
    monkeypatch.setattr("app.worker.process_aura_routing_ticket", _FakeTask())

    recovered = await worker._recover_stale_aura_routing_jobs()

    assert recovered == ["4099107"]
    assert status_updates == [
        {
            "ticket_id": "4099107",
            "status": "queued",
            "error": "Previous Aura routing job was interrupted; retrying.",
        }
    ]
    assert enqueued == ["4099107"]


def test_aura_retry_exhaustion_marks_ticket_failed(monkeypatch):
    status_updates = []

    async def fake_process(_ticket_id):
        await asyncio.sleep(0)
        raise worker._AuraRoutingRetry("Aura is rate-limiting routing requests.", 60)

    async def fake_set_status(_session, **kwargs):
        await asyncio.sleep(0)
        status_updates.append(kwargs)

    monkeypatch.setattr("app.worker._process_aura_routing_ticket", fake_process)
    monkeypatch.setattr("app.worker._driver_scope", _NullDriverScope)
    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(object()))
    monkeypatch.setattr("app.worker.queries.set_ticket_aura_routing_status", fake_set_status)

    task = worker.process_aura_routing_ticket
    task.push_request(retries=worker._AURA_MAX_RETRIES)
    try:
        with pytest.raises(RuntimeError):
            task.run("4099107")
    finally:
        task.pop_request()

    assert status_updates == [
        {
            "ticket_id": "4099107",
            "status": "failed",
            "error": "Aura routing retries exhausted: Aura is rate-limiting routing requests.",
        }
    ]


def test_soft_time_limit_kill_marks_ticket_failed(monkeypatch):
    status_updates = []

    async def fake_process(_ticket_id):
        await asyncio.sleep(0)
        raise SoftTimeLimitExceeded()

    async def fake_set_status(_session, **kwargs):
        await asyncio.sleep(0)
        status_updates.append(kwargs)

    monkeypatch.setattr("app.worker._process_aura_routing_ticket", fake_process)
    monkeypatch.setattr("app.worker._driver_scope", _NullDriverScope)
    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(object()))
    monkeypatch.setattr("app.worker.queries.set_ticket_aura_routing_status", fake_set_status)

    with pytest.raises(SoftTimeLimitExceeded):
        worker.process_aura_routing_ticket.run("4099107")

    assert status_updates == [
        {
            "ticket_id": "4099107",
            "status": "failed",
            "error": "Aura routing job timed out; use Reroute to retry.",
        }
    ]


@pytest.mark.asyncio
async def test_wait_for_aura_rate_slot_reserves_one_minute_start_slot():
    redis = _FakeRedis()

    await worker._wait_for_aura_rate_slot(redis, "4099107")

    assert redis.set_calls == [
        (
            (worker._AURA_RATE_SLOT_KEY, "4099107"),
            {"nx": True, "ex": worker._AURA_MIN_START_INTERVAL_SECONDS},
        )
    ]


@pytest.mark.asyncio
async def test_aura_cooldown_defers_without_calling_agent(monkeypatch):
    status_updates = []

    class _CooldownRedis(_FakeRedis):
        async def pttl(self, key):
            await asyncio.sleep(0)
            self.pttl_calls.append(key)
            return 125_000

    async def fake_set_status(_session, **kwargs):
        await asyncio.sleep(0)
        status_updates.append(kwargs)

    monkeypatch.setattr("app.worker.queries.set_ticket_aura_routing_status", fake_set_status)
    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(object()))

    with pytest.raises(worker._AuraRoutingRetry) as exc_info:
        await worker._defer_if_aura_cooldown_active(_CooldownRedis(), "4099107")

    assert exc_info.value.countdown == 126
    assert status_updates == [
        {
            "ticket_id": "4099107",
            "status": "queued",
            "error": "Aura is rate-limiting routing requests; retrying after cooldown.",
        }
    ]


@pytest.mark.asyncio
async def test_aura_lock_timeout_requeues_ticket_for_retry(monkeypatch):
    status_updates = []

    class _BusyRedis(_FakeRedis):
        async def set(self, *args, **kwargs):
            await asyncio.sleep(0)
            self.set_calls.append((args, kwargs))
            return False

    async def fake_has_recommendation(_session, _ticket_id):
        await asyncio.sleep(0)
        return False

    async def fake_set_status(_session, **kwargs):
        await asyncio.sleep(0)
        status_updates.append(kwargs)

    monkeypatch.setattr("app.worker.queries.has_routing_recommendation", fake_has_recommendation)
    monkeypatch.setattr("app.worker.queries.set_ticket_aura_routing_status", fake_set_status)
    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(object()))
    monkeypatch.setattr(
        "app.worker.Redis.from_url", lambda *_args, **_kwargs: _RedisContext(_BusyRedis())
    )
    monkeypatch.setattr("app.worker._AURA_LOCK_TIMEOUT", -1)

    with pytest.raises(worker._AuraRoutingRetry) as exc_info:
        await worker._process_aura_routing_ticket("4099107")

    assert exc_info.value.countdown == worker._AURA_TRANSIENT_RETRY_SECONDS
    assert status_updates == [
        {
            "ticket_id": "4099107",
            "status": "queued",
            "error": "Aura routing lock timeout for ticket 4099107; retrying.",
        }
    ]


@pytest.mark.asyncio
async def test_poll_teamwork_updates_runs_aura_recovery_when_auto_sync_disabled(monkeypatch):
    session = object()
    recovered = []

    async def fake_recover():
        await _async_value(None)
        recovered.append(True)
        return []

    async def fake_get_settings(_session):
        return await _async_value({"enabled": False, "interval_seconds": 60})

    async def fake_get_state(_session):
        return await _async_value({"cursor": "2026-05-24T22:00:00Z"})

    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.worker._recover_stale_aura_routing_jobs", fake_recover)
    monkeypatch.setattr("app.worker.is_full_import_running", lambda: _async_value(False))
    monkeypatch.setattr("app.worker.queries.get_teamwork_auto_sync_settings", fake_get_settings)
    monkeypatch.setattr("app.worker.queries.get_teamwork_update_sync_state", fake_get_state)

    await worker._poll_teamwork_updates()

    assert recovered == [True]


@pytest.mark.asyncio
async def test_poll_teamwork_updates_skips_sync_when_full_import_running(monkeypatch):
    recovered = []
    sync_calls = []

    async def fake_recover():
        await _async_value(None)
        recovered.append(True)
        return []

    async def fake_running():
        return await _async_value(True)

    async def fake_run_sync(*, enqueue_aura_routing_job):
        await _async_value(None)
        sync_calls.append(enqueue_aura_routing_job)
        return {"status": "ok"}

    monkeypatch.setattr("app.worker._recover_stale_aura_routing_jobs", fake_recover)
    monkeypatch.setattr("app.worker.is_full_import_running", fake_running)
    monkeypatch.setattr("app.worker.run_teamwork_sync_now", fake_run_sync)

    await worker._poll_teamwork_updates()

    assert recovered == [True]
    assert sync_calls == []


@pytest.mark.asyncio
async def test_poll_teamwork_updates_runs_sync_when_auto_sync_due(monkeypatch):
    session = object()
    recovered = []
    sync_calls = []

    async def fake_recover():
        await _async_value(None)
        recovered.append(True)
        return []

    async def fake_get_settings(_session):
        return await _async_value({"enabled": True, "interval_seconds": 60})

    async def fake_get_state(_session):
        return await _async_value(
            {"cursor": "2026-05-24T22:00:00Z", "last_run_at": "2026-05-24T22:00:00Z"}
        )

    async def fake_run_sync(*, enqueue_aura_routing_job):
        await _async_value(None)
        sync_calls.append(enqueue_aura_routing_job)
        return {"status": "ok"}

    monkeypatch.setattr("app.worker.db_context", lambda: _FakeDbContext(session))
    monkeypatch.setattr("app.worker._recover_stale_aura_routing_jobs", fake_recover)
    monkeypatch.setattr("app.worker.is_full_import_running", lambda: _async_value(False))
    monkeypatch.setattr("app.worker.queries.get_teamwork_auto_sync_settings", fake_get_settings)
    monkeypatch.setattr("app.worker.queries.get_teamwork_update_sync_state", fake_get_state)
    monkeypatch.setattr("app.worker.run_teamwork_sync_now", fake_run_sync)

    await worker._poll_teamwork_updates()

    assert recovered == [True]
    assert len(sync_calls) == 1
