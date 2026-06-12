import asyncio
import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from app import config
from app.main import app
from app.services import _http as _http_mod
from app.services import usage as usage_mod


class _BlockedHTTPClient:
    """Default async HTTP client for tests: refuses real outbound calls.

    Any test that exercises a Gemini path must install its own fake client; a
    forgotten mock then raises here instead of spending real API credits.
    """

    def __init__(self, *args, **kwargs) -> None:
        # Accepts httpx.AsyncClient's constructor signature but holds no state;
        # this stub never opens a connection.
        pass

    async def __aenter__(self) -> "_BlockedHTTPClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url, *args, **kwargs):
        raise RuntimeError(f"Real outbound HTTP blocked in tests (mock it): POST {url}")

    async def get(self, url, *args, **kwargs):
        raise RuntimeError(f"Real outbound HTTP blocked in tests (mock it): GET {url}")


class _NoOpRedis:
    """No-op Redis stand-in so best-effort spend counters never touch a real server."""

    @classmethod
    def from_url(cls, *args, **kwargs) -> "_NoOpRedis":
        return cls()

    async def __aenter__(self) -> "_NoOpRedis":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    def pipeline(self) -> "_NoOpRedis":
        return self

    def hincrby(self, *args, **kwargs) -> "_NoOpRedis":
        return self

    def expire(self, *args, **kwargs) -> "_NoOpRedis":
        return self

    async def execute(self) -> list:
        await asyncio.sleep(0)  # real await so this matches redis.asyncio's awaitable API
        return []


@pytest.fixture(autouse=True)
def _block_real_credit_spend(monkeypatch):
    """Stop any test from spending Gemini credits or emitting live Langfuse traces."""
    monkeypatch.setattr(config.settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(config.settings, "aura_trace_enabled", False)
    monkeypatch.setattr(config.settings, "langfuse_public_key", "")
    monkeypatch.setattr(config.settings, "langfuse_secret_key", "")
    monkeypatch.setattr(_http_mod.httpx, "AsyncClient", _BlockedHTTPClient)
    monkeypatch.setattr(usage_mod, "Redis", _NoOpRedis)
    yield


@pytest.fixture
async def client():
    from httpx import Cookies

    from app.services import auth as auth_svc

    cookies = Cookies()
    if auth_svc.auth_enabled():
        cookies.set(
            auth_svc.SESSION_COOKIE_NAME,
            auth_svc._sign_session(int(time.time())),
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=cookies,
    ) as c:
        yield c
