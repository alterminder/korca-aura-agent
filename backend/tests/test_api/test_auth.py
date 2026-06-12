import stat

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.services import auth as auth_svc


@pytest.fixture(autouse=True)
def enable_auth(monkeypatch):
    monkeypatch.setattr(settings, "korca_auth_password", "secret-pass")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "test-cookie-secret")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", "")
    auth_svc._reset_session_secret_cache_for_tests()
    yield
    auth_svc._reset_session_secret_cache_for_tests()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_health_remains_public_when_auth_is_enabled(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_protected_api_rejects_missing_session_cookie(client):
    response = await client.get("/api/stats")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_login_sets_session_cookie_and_allows_api_access(client):
    login = await client.post("/api/auth/login", json={"password": "secret-pass"})

    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert "korca_session" in client.cookies

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": True}

    protected = await client.get("/api/stats")
    # Auth middleware admits the request; the endpoint may 5xx without a
    # configured database, which is outside the scope of this auth test.
    assert protected.status_code != 401


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client):
    response = await client.post("/api/auth/login", json={"password": "wrong"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid password"
    assert "korca_session" not in client.cookies


@pytest.mark.asyncio
async def test_logout_clears_session_access(client):
    await client.post("/api/auth/login", json={"password": "secret-pass"})

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False}

    protected = await client.get("/api/stats")
    assert protected.status_code == 401


def test_cookie_secret_env_value_takes_precedence_over_file(tmp_path, monkeypatch):
    secret_path = tmp_path / "auth-cookie-secret"
    secret_path.write_text("file-secret", encoding="utf-8")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "env-secret")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", str(secret_path))

    assert auth_svc._secret() == b"env-secret"


def test_cookie_secret_file_is_generated_and_reused(tmp_path, monkeypatch):
    secret_path = tmp_path / "auth-cookie-secret"
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", str(secret_path))

    first = auth_svc._secret()

    assert secret_path.exists()
    assert first == secret_path.read_text(encoding="utf-8").strip().encode("utf-8")
    auth_svc._reset_session_secret_cache_for_tests()
    assert auth_svc._secret() == first
    assert first != b"secret-pass"


def test_cookie_secret_file_is_cached_after_first_read(tmp_path, monkeypatch):
    secret_path = tmp_path / "auth-cookie-secret"
    secret_path.write_text("file-secret", encoding="utf-8")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", str(secret_path))

    assert auth_svc._secret() == b"file-secret"
    secret_path.write_text("changed-secret", encoding="utf-8")
    assert auth_svc._secret() == b"file-secret"


def test_generated_cookie_secret_file_uses_restrictive_permissions(tmp_path, monkeypatch):
    secret_path = tmp_path / "auth-cookie-secret"
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", str(secret_path))

    auth_svc._secret()

    mode = stat.S_IMODE(secret_path.stat().st_mode)
    assert mode == 0o600


def test_existing_empty_cookie_secret_file_fails_startup(tmp_path, monkeypatch):
    secret_path = tmp_path / "auth-cookie-secret"
    secret_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret", "")
    monkeypatch.setattr(settings, "korca_auth_cookie_secret_file", str(secret_path))

    with pytest.raises(RuntimeError, match="cookie secret file is empty"):
        auth_svc.ensure_session_secret()
