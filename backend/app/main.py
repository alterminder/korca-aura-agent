from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import ServiceUnavailable, TransientError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import (
    aura_agents,
    auth,
    backup,
    clients,
    documents,
    evaluation,
    events,
    health,
    notifications,
    routing,
    search,
    teamwork_import,
    tickets,
    users,
)
from app.config import settings
from app.db.connection import close_driver, db_context, init_driver
from app.db.schema import init_schema
from app.exceptions import (
    AuraAgentError,
    DomainError,
    DomainValidationError,
    FileOversizedError,
    SyncConflictError,
    SyncNotBootstrappedError,
    TicketNotFoundError,
)
from app.limiter import limiter
from app.services import auth as auth_svc
from app.services._http import close_clients, setup_clients
from app.services.aura_tracing import shutdown_aura_trace_client

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Korca API")
    if auth_svc.auth_enabled():
        auth_svc.ensure_session_secret()
        if not settings.korca_auth_cookie_secret and not settings.korca_auth_cookie_secret_file:
            logger.warning(
                "korca_auth_cookie_secret_file is not set; session cookies use an "
                "ephemeral in-memory signing secret and will be invalid after restart."
            )
    await init_driver()
    await setup_clients()
    async with db_context() as session:
        await init_schema(session)
    yield
    await close_driver()
    await close_clients()
    shutdown_aura_trace_client()
    logger.info("Korca API stopped")


app = FastAPI(title="Korca API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ServiceUnavailable)
async def neo4j_unavailable_handler(request: Request, exc: ServiceUnavailable) -> JSONResponse:
    logger.error("neo4j_unavailable", path=request.url.path, error=str(exc))
    return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)


@app.exception_handler(TransientError)
async def neo4j_transient_handler(request: Request, exc: TransientError) -> JSONResponse:
    logger.error("neo4j_transient_error", path=request.url.path, error=str(exc))
    return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_codes = {
        TicketNotFoundError: 404,
        DomainValidationError: 400,
        FileOversizedError: 413,
        SyncConflictError: 409,
        SyncNotBootstrappedError: 409,
        AuraAgentError: 502,
    }
    status_code = status_codes.get(type(exc), 500)
    logger.warning(
        "domain_error",
        path=request.url.path,
        exc_type=type(exc).__name__,
        error=exc.message,
    )
    return JSONResponse({"detail": exc.message}, status_code=status_code)


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    if path == "/api/health" or path.startswith("/api/auth/"):
        return await call_next(request)
    if not auth_svc.request_is_authenticated(request):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return await call_next(request)


app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(teamwork_import.router, prefix="/api/import", tags=["import"])
app.include_router(tickets.router, prefix="/api/import", tags=["import"])
app.include_router(routing.router, prefix="/api/import", tags=["import"])
app.include_router(evaluation.router, prefix="/api/import", tags=["import"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(backup.router, prefix="/api/backup", tags=["backup"])
app.include_router(aura_agents.router, prefix="/api/aura", tags=["aura"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])

# Serve built React frontend in production
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    assets_path = static_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        file = static_path / full_path
        if file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(static_path / "index.html")
