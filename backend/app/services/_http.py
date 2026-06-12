"""Shared HTTP client infrastructure.

Provides:
- Shared constants and helpers for Gemini and Aura API calls.
- Module-level AsyncClient instances managed by the FastAPI lifespan.
- Context-manager accessors that use the pooled client in FastAPI context and
  fall back to a fresh per-call client in Celery workers (which run in a fresh
  event loop per task and cannot safely reuse a pooled client).
"""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog

from app.services.usage import log_gemini_spend

logger = structlog.get_logger()

GEMINI_API_BASE = "https://generativelanguage.googleapis.com"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_GENERATION_MODEL_RE = re.compile(r"/models/([^:/]+):generateContent")

# Set by setup_clients() during FastAPI lifespan startup; None in Celery workers.
_gemini: httpx.AsyncClient | None = None
_aura: httpx.AsyncClient | None = None


async def setup_clients() -> None:
    """Create module-level clients. Called once during FastAPI lifespan startup."""
    global _gemini, _aura
    _gemini = httpx.AsyncClient()
    _aura = httpx.AsyncClient()


async def close_clients() -> None:
    """Close module-level clients. Called during FastAPI lifespan shutdown."""
    global _gemini, _aura
    for client in (_gemini, _aura):
        if client is not None:
            await client.aclose()
    _gemini = None
    _aura = None


@asynccontextmanager
async def get_gemini_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield the shared Gemini client (FastAPI) or a fresh one (Celery)."""
    if _gemini is not None:
        yield _gemini
    else:
        async with httpx.AsyncClient() as client:
            yield client


@asynccontextmanager
async def get_aura_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield the shared Aura client (FastAPI) or a fresh one (Celery)."""
    if _aura is not None:
        yield _aura
    else:
        async with httpx.AsyncClient() as client:
            yield client


def _gemini_text(data: dict) -> str:
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(str(part.get("text", "")) for part in parts).strip()


async def _log_generation_spend(
    url: str, response: httpx.Response | None = None, *, result: str = "ok"
) -> None:
    """Record Gemini generateContent token spend from the response usageMetadata."""
    match = _GENERATION_MODEL_RE.search(url)
    if not match:
        return
    usage: dict = {}
    if response is not None:
        try:
            usage = response.json().get("usageMetadata") or {}
        except Exception:
            usage = {}
    await log_gemini_spend(
        kind="generate",
        model=match.group(1),
        requests=1,
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
        result=result,
    )


async def _post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    payload: dict,
    timeout: float,
    attempts: int = 3,
) -> httpx.Response:
    for attempt in range(1, attempts + 1):
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        try:
            response.raise_for_status()
            await _log_generation_spend(url, response)
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if attempt == attempts or status not in _RETRYABLE_STATUS_CODES:
                await _log_generation_spend(url, result="error")
                raise
            delay = float(attempt * 2)
            logger.warning(
                "gemini_request_retrying",
                attempt=attempt,
                status=status,
                delay=delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")
