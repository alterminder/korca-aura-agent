"""Aura routing accuracy routes."""

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

from app.db import queries
from app.db.connection import db_context

logger = structlog.get_logger()
router = APIRouter()


class RoutingAccuracyResponse(BaseModel):
    evaluated: int = 0
    correct: int = 0
    accuracy_pct: float | None = None


@router.get("/routing/ai-accuracy")
async def ai_routing_accuracy() -> RoutingAccuracyResponse:
    """Return Aura routing accuracy from RoutingEvent vs ASSIGNED_TO."""
    async with db_context() as session:
        data = await queries.get_aura_routing_accuracy(session)
    return RoutingAccuracyResponse.model_validate(data)
