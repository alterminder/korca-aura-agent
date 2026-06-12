from contextlib import asynccontextmanager
from typing import get_type_hints
from unittest.mock import AsyncMock

import pytest

from app.api.routes import evaluation


def _fake_db_context(session=None):
    @asynccontextmanager
    async def _cm():
        yield session

    return _cm


def test_ai_routing_accuracy_has_typed_response_model():
    annotation = get_type_hints(evaluation.ai_routing_accuracy)["return"]
    assert annotation.__name__ == "RoutingAccuracyResponse"


@pytest.mark.asyncio
async def test_ai_routing_accuracy_returns_typed_model(monkeypatch):
    monkeypatch.setattr(evaluation, "db_context", _fake_db_context())
    monkeypatch.setattr(
        evaluation.queries,
        "get_aura_routing_accuracy",
        AsyncMock(return_value={"evaluated": 10, "correct": 9, "accuracy_pct": 90.0}),
    )

    result = await evaluation.ai_routing_accuracy()

    assert type(result).__name__ == "RoutingAccuracyResponse"
    assert result.evaluated == 10
    assert result.correct == 9
    assert result.accuracy_pct == pytest.approx(90.0)


@pytest.mark.asyncio
async def test_ai_routing_accuracy_handles_no_data(monkeypatch):
    monkeypatch.setattr(evaluation, "db_context", _fake_db_context())
    monkeypatch.setattr(
        evaluation.queries,
        "get_aura_routing_accuracy",
        AsyncMock(return_value={"evaluated": 0, "correct": 0, "accuracy_pct": None}),
    )

    result = await evaluation.ai_routing_accuracy()

    assert result.evaluated == 0
    assert result.accuracy_pct is None
