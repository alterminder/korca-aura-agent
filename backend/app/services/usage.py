"""Gemini API spend logging and best-effort Redis usage counters.

Every Gemini call (embeddings + generation) funnels through `log_gemini_spend`,
so spend is visible in stdout logs (greppable as `gemini_spend`) and accumulated
into hourly Redis counters for an in-app usage view. Counter writes are
best-effort and never raise into the Gemini call path.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis

from app.config import settings

logger = structlog.get_logger()

_SPEND_KEY_PREFIX = "korca:spend"
_SPEND_TTL_SECONDS = 100 * 24 * 3600  # ~100-day rolling window


def estimate_tokens(texts: list[str]) -> int:
    """Approximate token count for embedding inputs.

    Gemini `batchEmbedContents` returns no usage metadata, so embedding token
    counts are estimated with a ~4-characters-per-token heuristic.
    """
    return sum(len(t) for t in texts) // 4


async def log_gemini_spend(
    *,
    kind: str,
    model: str,
    requests: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    result: str = "ok",
    **context: Any,
) -> None:
    """Emit a structured `gemini_spend` log and increment Redis counters.

    `context` (e.g. ticket_id, source) is attached to the log line only — it is
    deliberately not used in counter keys, to keep counter cardinality low.
    """
    logger.info(
        "gemini_spend",
        kind=kind,
        model=model,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        result=result,
        **context,
    )
    await _record_spend(
        kind=kind,
        model=model,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        result=result,
    )


async def _record_spend(
    *,
    kind: str,
    model: str,
    requests: int,
    input_tokens: int,
    output_tokens: int,
    result: str,
) -> None:
    """Increment hourly Redis spend counters. Best-effort: never raises."""
    if not settings.redis_url:
        return
    try:
        bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H")
        key = f"{_SPEND_KEY_PREFIX}:{bucket}"
        base = f"{kind}|{model}"
        async with Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ) as r:
            pipe = r.pipeline()
            pipe.hincrby(key, f"{base}|requests", requests)
            pipe.hincrby(key, f"{base}|input_tokens", input_tokens)
            pipe.hincrby(key, f"{base}|output_tokens", output_tokens)
            if result != "ok":
                pipe.hincrby(key, f"{base}|errors", requests)
            pipe.expire(key, _SPEND_TTL_SECONDS)
            await pipe.execute()
    except Exception as exc:  # counters must never break a Gemini call
        logger.warning("gemini_spend_record_failed", error=str(exc))
