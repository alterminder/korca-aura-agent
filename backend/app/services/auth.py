from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import Request, Response

from app.config import settings

SESSION_COOKIE_NAME = "korca_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
COOKIE_SECRET_BYTES = 48
_SESSION_SECRET: bytes | None = None
_EPHEMERAL_COOKIE_SECRET: str | None = None


def auth_enabled() -> bool:
    return bool(settings.korca_auth_password)


def password_matches(password: str) -> bool:
    return hmac.compare_digest(password, settings.korca_auth_password)


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        _sign_session(int(time.time())),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.korca_auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")


def request_is_authenticated(request: Request) -> bool:
    if not auth_enabled():
        return True
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return bool(token and _verify_session(token))


def _secret() -> bytes:
    return ensure_session_secret()


def ensure_session_secret() -> bytes:
    global _SESSION_SECRET
    secret = _SESSION_SECRET
    if secret is None:
        secret = _resolve_session_secret()
        _SESSION_SECRET = secret
    return secret


def _resolve_session_secret() -> bytes:
    explicit_secret = settings.korca_auth_cookie_secret.strip()
    if explicit_secret:
        return explicit_secret.encode("utf-8")

    secret_file = settings.korca_auth_cookie_secret_file.strip()
    if secret_file:
        return _read_or_create_cookie_secret(Path(secret_file)).encode("utf-8")

    return _ephemeral_cookie_secret().encode("utf-8")


def _read_or_create_cookie_secret(path: Path) -> str:
    if path.exists():
        return _read_cookie_secret_file(path)

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = secrets.token_urlsafe(COOKIE_SECRET_BYTES)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_cookie_secret_file(path)

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{value}\n")
    return value


def _read_cookie_secret_file(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"cookie secret file is empty: {path}")
    return value


def _ephemeral_cookie_secret() -> str:
    global _EPHEMERAL_COOKIE_SECRET
    if _EPHEMERAL_COOKIE_SECRET is None:
        _EPHEMERAL_COOKIE_SECRET = secrets.token_urlsafe(COOKIE_SECRET_BYTES)
    return _EPHEMERAL_COOKIE_SECRET


def _reset_session_secret_cache_for_tests() -> None:
    global _SESSION_SECRET, _EPHEMERAL_COOKIE_SECRET
    _SESSION_SECRET = None
    _EPHEMERAL_COOKIE_SECRET = None


def _sign_session(created_at: int) -> str:
    payload = str(created_at)
    signature = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _verify_session(token: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        created_at_raw, signature = raw.rsplit(":", 1)
        created_at = int(created_at_raw)
    except (ValueError, UnicodeDecodeError):
        return False

    if time.time() - created_at > SESSION_TTL_SECONDS:
        return False

    expected = hmac.new(_secret(), created_at_raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
