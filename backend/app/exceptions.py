"""Custom domain exceptions to decouple business logic from FastAPI HTTP exceptions."""


class DomainError(Exception):
    """Base exception for all application domain errors."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class DomainValidationError(DomainError):
    """Raised when request data fails domain validation rules (e.g. non-numeric ID)."""

    pass


class TicketNotFoundError(DomainError):
    """Raised when a ticket is not found in the database."""

    pass


class FileOversizedError(DomainError):
    """Raised when an uploaded file exceeds the configured size limit."""

    pass


class SyncConflictError(DomainError):
    """Raised when there is a state/concurrency conflict (e.g. sync already running)."""

    pass


class SyncNotBootstrappedError(DomainError):
    """Raised when a sync operation is attempted before the system is bootstrapped."""

    pass


class AuraAgentError(DomainError):
    """Raised when the external Neo4j Aura agent returns an error or invalid response."""

    pass
