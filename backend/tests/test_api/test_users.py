from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.routes import users


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.users.", "")


def test_user_route_handlers_have_typed_response_models():
    assert _return_annotation_name(users.list_users) == "list[UserResponse]"
    assert _return_annotation_name(users.create_user) == "UserResponse"
    assert _return_annotation_name(users.update_user_profile) == "UserResponse"
    assert _return_annotation_name(users.compare_experts) == "ExpertComparisonResponse"
    assert _return_annotation_name(users.get_user) == "UserDetailResponse"


@pytest.mark.asyncio
async def test_list_users_returns_response_models_from_cache(monkeypatch):
    monkeypatch.setattr(
        users,
        "get_cached_data",
        AsyncMock(
            return_value=[
                {
                    "id": "user_123",
                    "email": "expert@example.com",
                    "name": "Example Expert",
                    "title": "Support Engineer",
                    "department": "Support",
                    "tickets_resolved": 3,
                    "topics": ["dns"],
                    "skills": ["cloudflare"],
                }
            ]
        ),
    )

    result = await users.list_users(object())

    assert [type(item).__name__ for item in result] == ["UserResponse"]
    assert result[0].email == "expert@example.com"


@pytest.mark.asyncio
async def test_get_user_tolerates_sparse_authored_documents(monkeypatch):
    monkeypatch.setattr(
        users.queries,
        "get_user",
        AsyncMock(
            return_value={
                "id": "user_123",
                "email": "expert@example.com",
                "name": "Example Expert",
                "skills": [],
            }
        ),
    )
    monkeypatch.setattr(
        users.queries,
        "get_user_authored_docs",
        AsyncMock(return_value=[{"id": "doc_123", "title": "Legacy doc", "created_at": None}]),
    )

    result = await users.get_user("user_123", object())

    assert type(result).__name__ == "UserDetailResponse"
    assert len(result.authored_documents) == 1
    assert result.authored_documents[0].title == "Legacy doc"
    assert result.authored_documents[0].created_at is None


@pytest.mark.asyncio
async def test_compare_experts_returns_response_model_with_nullable_client_names(monkeypatch):
    monkeypatch.setattr(
        users.queries,
        "compare_experts",
        AsyncMock(
            return_value={
                "expert_a": {"id": "a", "name": "Alice", "email": "alice@example.com"},
                "expert_b": {"id": "b", "name": "Bob", "email": "bob@example.com"},
                "shared_clients": [{"name": None, "count_a": 2, "count_b": 3}],
                "only_a_clients": [{"name": None, "count": 1}],
                "only_b_clients": [],
                "shared_skills": [],
                "only_a_skills": [],
                "only_b_skills": [],
            }
        ),
    )

    result = await users.compare_experts("a", "b", object())

    assert type(result).__name__ == "ExpertComparisonResponse"
    assert result.shared_clients[0].name is None
    assert result.only_a_clients[0].name is None


@pytest.mark.asyncio
async def test_update_user_profile_logs_traceback_when_skill_embedding_fails(monkeypatch):
    fake_logger = Mock()
    monkeypatch.setattr(users, "logger", fake_logger)
    monkeypatch.setattr(users.queries, "get_user", AsyncMock(return_value={"skills": ["old skill"]}))
    monkeypatch.setattr(users, "_embed_skills", AsyncMock(side_effect=RuntimeError("downstream")))

    with pytest.raises(HTTPException) as exc_info:
        await users.update_user_profile(
            "user_123",
            users.UserProfileUpdate(skills=["new skill"]),
            object(),
        )

    assert exc_info.value.status_code == 502
    fake_logger.warning.assert_called_once_with(
        "user_profile_skill_embedding_failed",
        user_id="user_123",
        exc_info=True,
    )
