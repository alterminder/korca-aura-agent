from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import settings

logger = structlog.get_logger()

_driver: AsyncDriver | None = None


def _required_aura_setting(name: str) -> str:
    value = str(getattr(settings, name, "") or "").strip()
    if not value:
        raise RuntimeError(f"{name.upper()} is required; korca-aura only supports Neo4j Aura")
    return value


async def init_driver(verify: bool = True) -> None:
    global _driver
    uri = _required_aura_setting("neo4j_uri_aura")
    _driver = AsyncGraphDatabase.driver(
        uri,
        auth=(
            _required_aura_setting("neo4j_user_aura"),
            _required_aura_setting("neo4j_pass_aura"),
        ),
    )
    if verify:
        await _driver.verify_connectivity()
    logger.info("Neo4j driver initialized", uri=uri, verified=verify)


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


def _get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized — call init_driver() first")
    return _driver


async def get_db() -> AsyncGenerator:
    """FastAPI dependency: yields an authenticated Neo4j session."""
    async with _get_driver().session(
        database=_required_aura_setting("neo4j_database_aura")
    ) as session:
        yield session


@asynccontextmanager
async def db_context() -> AsyncGenerator:
    """Context manager for background tasks outside FastAPI DI."""
    async with _get_driver().session(
        database=_required_aura_setting("neo4j_database_aura")
    ) as session:
        yield session
