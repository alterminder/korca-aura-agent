"""Optional Langfuse tracing for the Aura routing demo path."""

from __future__ import annotations

import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger()

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"]+|www\.[^\s<>\"]+", re.IGNORECASE)
_TOKEN_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;]+"
)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_-]{31,}\b")

_LANGFUSE_CLIENT: Any | None = None


@dataclass(slots=True)
class AuraTraceOutcome:
    response: dict[str, Any] | None
    trace_id: str | None
    latency_ms: int
    error: Exception | None = None


def redact_preview(text: str | None, max_chars: int = 500) -> str:
    """Return a compact, redacted preview suitable for external trace storage."""
    if not text:
        return ""

    redacted = _EMAIL_RE.sub("[redacted-email]", text)
    redacted = _URL_RE.sub("[redacted-url]", redacted)
    redacted = _TOKEN_ASSIGNMENT_RE.sub("[redacted-token]", redacted)
    redacted = _LONG_TOKEN_RE.sub("[redacted-token]", redacted)
    redacted = re.sub(r"\s+", " ", redacted).strip()

    if len(redacted) <= max_chars:
        return redacted
    return f"{redacted[: max_chars - 1].rstrip()}…"


def _should_trace() -> bool:
    if not (
        settings.aura_trace_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
        and settings.aura_trace_sample_rate > 0
    ):
        return False
    sample_rate = max(0.0, min(settings.aura_trace_sample_rate, 1.0))
    return secrets.randbelow(1_000_000) < round(sample_rate * 1_000_000)


def _get_langfuse_client() -> Any | None:
    global _LANGFUSE_CLIENT
    if _LANGFUSE_CLIENT is not None:
        return _LANGFUSE_CLIENT
    try:
        from langfuse import Langfuse

        _LANGFUSE_CLIENT = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url or None,
            tracing_enabled=True,
            # Sampling is decided in _should_trace before observation creation,
            # so we always emit observations we start.
            sample_rate=1.0,
            environment=settings.korca_env,
        )
    except Exception as exc:
        logger.warning("aura_trace_langfuse_unavailable", error=str(exc))
        return None
    return _LANGFUSE_CLIENT


def _response_text(response: dict[str, Any] | None) -> str:
    if not response:
        return ""
    output = response.get("output")
    if isinstance(output, str) and output:
        return output
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                return text
    return ""


async def trace_aura_route_call(
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    ticket_id: str,
    subject: str,
    content: str,
    client_name: str,
) -> AuraTraceOutcome:
    """Run an Aura route call with optional Langfuse tracing.

    Never raises the routed call's exception — returns it on the outcome so
    the caller can persist trace metadata before reacting.
    """
    start = time.perf_counter()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - start) * 1000)

    lf = _get_langfuse_client() if _should_trace() else None
    if lf is None:
        try:
            return AuraTraceOutcome(response=await call(), trace_id=None, latency_ms=elapsed_ms())
        except Exception as exc:
            return AuraTraceOutcome(
                response=None, trace_id=None, latency_ms=elapsed_ms(), error=exc
            )

    trace_id = uuid.uuid4().hex
    input_payload = {
        "ticket_id": ticket_id,
        "client_name": redact_preview(client_name, max_chars=120),
        "subject_preview": redact_preview(subject, max_chars=160),
        "input_preview": redact_preview(content, max_chars=700),
    }

    response: dict[str, Any] | None = None
    error: Exception | None = None
    # Outer try shields against Langfuse SDK failures inside __enter__/__exit__
    # (e.g. transport errors). Inner try captures the routed call's own error
    # without confusing it with the SDK error.
    try:
        with lf.start_as_current_observation(
            as_type="agent",
            name="aura.route_ticket",
            input=input_payload,
            trace_context={"trace_id": trace_id},
        ) as span:
            try:
                response = await call()
            except Exception as exc:
                error = exc
            _safe_span_update(span, response, error, elapsed_ms())
    except Exception as exc:
        logger.warning("aura_trace_sdk_error", ticket_id=ticket_id, error=str(exc))
        # Preserve whatever the routed call produced; only surface SDK error
        # when we have nothing else.
        if response is None and error is None:
            error = exc

    return AuraTraceOutcome(
        response=response, trace_id=trace_id, latency_ms=elapsed_ms(), error=error
    )


def _safe_span_update(
    span: Any, response: dict[str, Any] | None, error: Exception | None, latency_ms: int
) -> None:
    if error is not None:
        output = {"status": "error", "error": redact_preview(str(error), max_chars=300)}
        metadata = {"status": "error", "latency_ms": latency_ms}
    else:
        output = {
            "status": "success",
            "response_preview": redact_preview(_response_text(response), max_chars=700),
        }
        metadata = {"status": "success", "latency_ms": latency_ms}
    try:
        span.update(output=output, metadata=metadata)
    except Exception as exc:
        logger.debug("aura_trace_span_update_failed", error=str(exc))


def shutdown_aura_trace_client() -> None:
    """Flush and close the Langfuse client during application shutdown."""
    global _LANGFUSE_CLIENT
    if _LANGFUSE_CLIENT is None:
        return
    shutdown = getattr(_LANGFUSE_CLIENT, "shutdown", None) or getattr(
        _LANGFUSE_CLIENT, "flush", None
    )
    try:
        if callable(shutdown):
            shutdown()
    except Exception as exc:
        logger.debug("aura_trace_shutdown_error", error=str(exc))
    finally:
        _LANGFUSE_CLIENT = None
