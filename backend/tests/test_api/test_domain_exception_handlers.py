import pytest

from app.exceptions import (
    AuraAgentError,
    DomainValidationError,
    FileOversizedError,
    SyncConflictError,
    SyncNotBootstrappedError,
    TicketNotFoundError,
)
from app.main import app


@pytest.mark.asyncio
async def test_domain_error_handler_status_codes(client):
    # Add a temporary test route to trigger the exceptions
    @app.get("/api/test-exception")
    async def trigger_exception(type_: str):
        if type_ == "not_found":
            raise TicketNotFoundError("Ticket missing")
        elif type_ == "validation":
            raise DomainValidationError("Invalid data")
        elif type_ == "oversized":
            raise FileOversizedError("Too big")
        elif type_ == "conflict":
            raise SyncConflictError("Sync active")
        elif type_ == "not_bootstrapped":
            raise SyncNotBootstrappedError("No cursor")
        elif type_ == "aura":
            raise AuraAgentError("Aura failed")
        return {"status": "ok"}

    try:
        # 1. TicketNotFoundError -> 404
        resp = await client.get("/api/test-exception?type_=not_found")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Ticket missing"

        # 2. DomainValidationError -> 400
        resp = await client.get("/api/test-exception?type_=validation")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid data"

        # 3. FileOversizedError -> 413
        resp = await client.get("/api/test-exception?type_=oversized")
        assert resp.status_code == 413
        assert resp.json()["detail"] == "Too big"

        # 4. SyncConflictError -> 409
        resp = await client.get("/api/test-exception?type_=conflict")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Sync active"

        # 5. SyncNotBootstrappedError -> 409
        resp = await client.get("/api/test-exception?type_=not_bootstrapped")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "No cursor"

        # 6. AuraAgentError -> 502
        resp = await client.get("/api/test-exception?type_=aura")
        assert resp.status_code == 502
        assert resp.json()["detail"] == "Aura failed"

    finally:
        # Remove the temporary route to avoid polluting the app state
        app.routes[:] = [r for r in app.routes if r.path != "/api/test-exception"]
