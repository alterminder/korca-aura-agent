import sys

import pytest

from app.services import aura_tracing


def test_redact_preview_masks_sensitive_values_and_truncates():
    text = (
        "Contact alice@example.com at https://example.com/reset "
        "Authorization: Bearer sk_test_abcdefghijklmnopqrstuvwxyz123456 " + ("long body " * 80)
    )

    redacted = aura_tracing.redact_preview(text, max_chars=180)

    assert "alice@example.com" not in redacted
    assert "https://example.com/reset" not in redacted
    assert "sk_test_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "[redacted-email]" in redacted
    assert "[redacted-url]" in redacted
    assert "[redacted-token]" in redacted
    assert len(redacted) <= 181
    assert redacted.endswith("…")


@pytest.mark.asyncio
async def test_trace_aura_route_call_noops_when_disabled(monkeypatch):
    monkeypatch.setattr(aura_tracing.settings, "aura_trace_enabled", False)
    monkeypatch.setattr(aura_tracing.settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(aura_tracing.settings, "langfuse_secret_key", "sk-test")

    async def call():
        return {"output": "RECOMMENDED: expert@example.com"}

    outcome = await aura_tracing.trace_aura_route_call(
        call,
        ticket_id="123",
        subject="Login issue",
        content="Email alice@example.com and visit https://example.com",
        client_name="Acme",
    )

    assert outcome.response == {"output": "RECOMMENDED: expert@example.com"}
    assert outcome.trace_id is None
    assert outcome.error is None
    assert outcome.latency_ms >= 0


@pytest.mark.asyncio
async def test_trace_aura_route_call_sends_redacted_langfuse_span(monkeypatch):
    captured = {}

    class FakeSpan:
        trace_id = "0123456789abcdef0123456789abcdef"

        def __init__(self, *, input_payload):
            captured["input"] = input_payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, **kwargs):
            captured.setdefault("updates", []).append(kwargs)

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            captured["span_args"] = kwargs
            return FakeSpan(input_payload=kwargs["input"])

        def flush(self):
            captured["flushed"] = True

    class FakeUUID:
        hex = FakeSpan.trace_id

    monkeypatch.setattr(aura_tracing.settings, "aura_trace_enabled", True)
    monkeypatch.setattr(aura_tracing.settings, "aura_trace_sample_rate", 1.0)
    monkeypatch.setattr(aura_tracing.settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(aura_tracing.settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(aura_tracing, "_get_langfuse_client", FakeLangfuse)
    monkeypatch.setattr(aura_tracing.uuid, "uuid4", FakeUUID)

    async def call():
        return {"output": "Ask bob@example.com to open https://internal.example/ticket"}

    outcome = await aura_tracing.trace_aura_route_call(
        call,
        ticket_id="123",
        subject="Login alice@example.com",
        content="Token api_key=abcdefghijklmnopqrstuvwxyz1234567890",
        client_name="Acme",
    )

    assert outcome.trace_id == FakeSpan.trace_id
    assert outcome.response == {
        "output": "Ask bob@example.com to open https://internal.example/ticket"
    }
    assert captured["span_args"]["name"] == "aura.route_ticket"
    assert captured["span_args"]["as_type"] == "agent"
    assert captured["span_args"]["trace_context"] == {"trace_id": FakeSpan.trace_id}
    assert captured["input"]["ticket_id"] == "123"
    assert "alice@example.com" not in captured["input"]["subject_preview"]
    assert "api_key=abcdefghijklmnopqrstuvwxyz1234567890" not in captured["input"]["input_preview"]
    assert "bob@example.com" not in captured["updates"][0]["output"]["response_preview"]
    response_preview = captured["updates"][0]["output"]["response_preview"]
    assert "https://internal.example/ticket" not in response_preview
    assert captured["updates"][0]["metadata"]["status"] == "success"


def test_get_langfuse_client_uses_wrapper_sampling_before_sdk_sampling(monkeypatch):
    captured = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(aura_tracing.settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(aura_tracing.settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(aura_tracing.settings, "langfuse_base_url", "https://cloud.langfuse.com")
    monkeypatch.setattr(aura_tracing.settings, "aura_trace_sample_rate", 0.25)
    monkeypatch.setattr(aura_tracing, "_LANGFUSE_CLIENT", None)
    fake_module = type("LangfuseModule", (), {"Langfuse": FakeLangfuse})
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)

    aura_tracing._get_langfuse_client()

    assert captured["sample_rate"] == pytest.approx(1.0)
    assert captured["base_url"] == "https://cloud.langfuse.com"


def test_shutdown_aura_trace_client_shutdowns_cached_client(monkeypatch):
    calls = []

    class FakeLangfuse:
        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr(aura_tracing, "_LANGFUSE_CLIENT", FakeLangfuse())

    aura_tracing.shutdown_aura_trace_client()

    assert calls == ["shutdown"]
    assert aura_tracing._LANGFUSE_CLIENT is None


@pytest.mark.asyncio
async def test_trace_aura_route_call_handles_context_manager_exception_gracefully(monkeypatch):
    class ExplodingSpan:
        trace_id = "abc123hex"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            raise RuntimeError("Langfuse database connection error during exit")

        def update(self, **kwargs):
            pass

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs):
            return ExplodingSpan()

    monkeypatch.setattr(aura_tracing.settings, "aura_trace_enabled", True)
    monkeypatch.setattr(aura_tracing.settings, "aura_trace_sample_rate", 1.0)
    monkeypatch.setattr(aura_tracing.settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(aura_tracing.settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(aura_tracing, "_get_langfuse_client", FakeLangfuse)

    async def call():
        return {"output": "SUCCESSFUL_ROUTE"}

    # Call should succeed despite the context manager throwing an exception on exit
    outcome = await aura_tracing.trace_aura_route_call(
        call,
        ticket_id="123",
        subject="Test subject",
        content="Test content",
        client_name="Test client",
    )

    assert outcome.response == {"output": "SUCCESSFUL_ROUTE"}
    assert len(outcome.trace_id) == 32
    assert outcome.error is None
