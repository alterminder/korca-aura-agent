from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.limiter import limiter
from app.services import auth as auth_svc

router = APIRouter()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AuthState(BaseModel):
    authenticated: bool


@router.get("/me")
async def me(request: Request) -> AuthState:
    return AuthState(authenticated=auth_svc.request_is_authenticated(request))


@router.post("/login", responses={401: {"description": "Invalid password"}})
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, response: Response) -> AuthState:
    if auth_svc.auth_enabled() and not auth_svc.password_matches(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    if auth_svc.auth_enabled():
        auth_svc.set_session_cookie(response)
    return AuthState(authenticated=True)


@router.post("/logout")
async def logout(response: Response) -> AuthState:
    auth_svc.clear_session_cookie(response)
    return AuthState(authenticated=False)
