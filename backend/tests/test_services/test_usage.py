import asyncio
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from app.services import usage


def test_estimate_tokens_uses_char_heuristic():
    # 8 characters total // 4 chars-per-token = 2
    assert usage.estimate_tokens(["abcd", "efgh"]) == 2
    assert usage.estimate_tokens([]) == 0


@pytest.mark.asyncio
async def test_log_gemini_spend_emits_event_and_keeps_context_out_of_counters(monkeypatch):
    record = AsyncMock()
    monkeypatch.setattr(usage, "_record_spend", record)

    with capture_logs() as logs:
        await usage.log_gemini_spend(
            kind="embed",
            model="gemini-embedding-001",
            requests=3,
            input_tokens=120,
            ticket_id="555",
            source="teamwork_sync",
        )

    event = next(e for e in logs if e["event"] == "gemini_spend")
    assert event["kind"] == "embed"
    assert event["requests"] == 3
    assert event["ticket_id"] == "555"
    assert event["source"] == "teamwork_sync"

    # Counters receive the metrics but not the high-cardinality context.
    record.assert_awaited_once()
    counters = record.await_args.kwargs
    assert counters["requests"] == 3
    assert counters["input_tokens"] == 120
    assert "ticket_id" not in counters
    assert "source" not in counters


@pytest.mark.asyncio
async def test_record_spend_increments_hourly_counters(monkeypatch):
    cmds: list = []

    class _RecordingRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def pipeline(self):
            return self

        def hincrby(self, key, field, n):
            cmds.append((field, n))
            return self

        def expire(self, key, ttl):
            cmds.append(("expire", ttl))
            return self

        async def execute(self):
            await asyncio.sleep(0)
            return []

    monkeypatch.setattr(usage.settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(usage, "Redis", _RecordingRedis)

    await usage._record_spend(
        kind="embed",
        model="m",
        requests=2,
        input_tokens=40,
        output_tokens=0,
        result="ok",
    )

    assert ("embed|m|requests", 2) in cmds
    assert ("embed|m|input_tokens", 40) in cmds
    assert ("embed|m|output_tokens", 0) in cmds
    assert any(c[0] == "expire" for c in cmds)
    # No error field is written on a successful call.
    assert all("errors" not in str(c[0]) for c in cmds)


@pytest.mark.asyncio
async def test_record_spend_noops_without_redis_url(monkeypatch):
    monkeypatch.setattr(usage.settings, "redis_url", "")

    def _boom(*args, **kwargs):
        raise AssertionError("Redis must not be touched when redis_url is empty")

    monkeypatch.setattr(usage, "Redis", _boom)

    # Should return cleanly without instantiating Redis.
    await usage._record_spend(
        kind="generate", model="m", requests=1, input_tokens=1, output_tokens=1, result="ok"
    )
