import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

_SLOW_QUERY_MS = 500
F = TypeVar("F", bound=Callable[..., Any])


def _log_slow(fn: F) -> F:
    """Wrap an async query function to log duration and warn on slow execution."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = await fn(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > _SLOW_QUERY_MS:
            logger.warning(
                "slow_query",
                query=fn.__name__,
                duration_ms=round(elapsed_ms),
                threshold_ms=_SLOW_QUERY_MS,
            )
        else:
            logger.debug("query_ok", query=fn.__name__, duration_ms=round(elapsed_ms))
        return result

    return wrapper  # type: ignore[return-value]


def user_uid(email: str) -> str:
    """Derive the canonical synthetic User.id from an email address."""
    return f"user_{email.replace('@', '_').replace('.', '_')}"
