"""Verifies the autouse guardrail in conftest.py prevents real credit spend."""

import pytest

from app import config
from app.services._http import get_gemini_client


def test_guardrail_forces_safe_settings():
    assert config.settings.gemini_api_key == "test-gemini-key"
    assert config.settings.aura_trace_enabled is False
    assert config.settings.langfuse_public_key == ""
    assert config.settings.langfuse_secret_key == ""


@pytest.mark.asyncio
async def test_unmocked_gemini_call_is_blocked():
    # No per-test fake installed → the autouse guardrail must block real HTTP
    # so a forgotten mock fails loudly instead of spending credits.
    with pytest.raises(RuntimeError, match="blocked in tests"):
        async with get_gemini_client() as client:
            await client.post("https://generativelanguage.googleapis.com/v1beta/x")
