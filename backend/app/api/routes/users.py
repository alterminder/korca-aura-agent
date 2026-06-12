from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DBDep
from app.db import queries
from app.services.embeddings import generate_embeddings
from app.services.llm import generate_expert_skills
from app.services.redis_cache import (
    CACHE_KEY_EXPERTS,
    get_cached_data,
    invalidate_cache,
    set_cached_data,
)

logger = structlog.get_logger()

router = APIRouter()


async def _embed_skills(skills: list[str]) -> dict[str, list[float]]:
    """Return {skill_lowercase: embedding} for a list of skill names."""
    if not skills:
        return {}
    clean = [s.strip() for s in skills if s.strip()]
    if not clean:
        return {}
    embeddings = await generate_embeddings(clean)
    return {s.lower(): emb for s, emb in zip(clean, embeddings, strict=True)}


class UserProfileUpdate(BaseModel):
    department: str | None = None
    title: str | None = None
    manager_email: str | None = None
    skills: list[str] | None = None


class CreateUserRequest(BaseModel):
    name: str
    email: str
    title: str | None = None
    department: str | None = None
    skills: list[str] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    title: str | None = None
    department: str | None = None
    manager_name: str | None = None
    manager_email: str | None = None
    certifications: list[str] = Field(default_factory=list)
    tickets_resolved: int | None = None
    topics: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class AuthoredDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    title: str | None = None
    status: str | None = None
    created_at: Any = None


class UserDetailResponse(UserResponse):
    authored_documents: list[AuthoredDocumentResponse] = Field(default_factory=list)


class ComparedExpertItem(BaseModel):
    id: str
    name: str
    email: str


class SharedClientComparisonItem(BaseModel):
    name: str | None = None
    count_a: int
    count_b: int


class ClientComparisonItem(BaseModel):
    name: str | None = None
    count: int


class ExpertComparisonResponse(BaseModel):
    expert_a: ComparedExpertItem
    expert_b: ComparedExpertItem
    shared_clients: list[SharedClientComparisonItem] = Field(default_factory=list)
    only_a_clients: list[ClientComparisonItem] = Field(default_factory=list)
    only_b_clients: list[ClientComparisonItem] = Field(default_factory=list)
    shared_skills: list[str] = Field(default_factory=list)
    only_a_skills: list[str] = Field(default_factory=list)
    only_b_skills: list[str] = Field(default_factory=list)


class GenerateSkillsResponse(BaseModel):
    skills: list[str]


def _user_response(data: dict[str, Any]) -> UserResponse:
    return UserResponse.model_validate(data)


def _user_responses(rows: list[dict[str, Any]]) -> list[UserResponse]:
    return [_user_response(row) for row in rows]


@router.get("")
async def list_users(db: DBDep) -> list[UserResponse]:
    cached = await get_cached_data(CACHE_KEY_EXPERTS)
    if isinstance(cached, list):
        return _user_responses(cached)
    data = await queries.list_users(db)
    await set_cached_data(CACHE_KEY_EXPERTS, data)
    return _user_responses(data)


@router.post("", status_code=201, responses={422: {"description": "name and email are required"}})
async def create_user(body: CreateUserRequest, db: DBDep) -> UserResponse:
    """Create a new expert manually (e.g. new employee before any tickets)."""
    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=422, detail="name and email are required")
    skill_embeddings = await _embed_skills(body.skills)
    user = await queries.create_user(
        db,
        name=body.name.strip(),
        email=body.email.strip().lower(),
        title=body.title or None,
        department=body.department or None,
        skills=body.skills,
        skill_embeddings=skill_embeddings,
    )
    await invalidate_cache(CACHE_KEY_EXPERTS)
    return _user_response(user)


@router.patch(
    "/{user_id}/profile",
    responses={
        404: {"description": "User not found"},
        502: {"description": "Upstream embedding service unavailable"},
    },
)
async def update_user_profile(user_id: str, body: UserProfileUpdate, db: DBDep) -> UserResponse:
    existing = await queries.get_user(db, user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing_skills: list[str] = existing.get("skills") or []
    skills_changed = body.skills is not None and sorted(body.skills) != sorted(existing_skills)
    skill_embeddings: dict[str, list[float]] = {}
    if skills_changed:
        try:
            skill_embeddings = await _embed_skills(body.skills)  # type: ignore[arg-type]
        except Exception:
            logger.warning(
                "user_profile_skill_embedding_failed",
                user_id=user_id,
                exc_info=True,
            )
            raise HTTPException(status_code=502, detail="Skill embedding failed — please try again")
    updated = await queries.update_user_profile(
        db,
        user_id,
        department=body.department,
        title=body.title,
        manager_email=body.manager_email,
        skills=body.skills,
        skill_embeddings=skill_embeddings,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    user = await queries.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await invalidate_cache(CACHE_KEY_EXPERTS)
    return _user_response(user)


@router.get(
    "/compare",
    responses={
        422: {"description": "Cannot compare an expert to themselves"},
        404: {"description": "One or both experts not found"},
    },
)
async def compare_experts(a: str, b: str, db: DBDep) -> ExpertComparisonResponse:
    """Return shared/exclusive clients and skills for two experts."""
    if a == b:
        raise HTTPException(status_code=422, detail="Cannot compare an expert to themselves")
    result = await queries.compare_experts(db, id_a=a, id_b=b)
    if not result:
        raise HTTPException(status_code=404, detail="One or both experts not found")
    return ExpertComparisonResponse.model_validate(result)


@router.get("/{user_id}", responses={404: {"description": "User not found"}})
async def get_user(user_id: str, db: DBDep) -> UserDetailResponse:
    user = await queries.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    docs = await queries.get_user_authored_docs(db, user_id)
    return UserDetailResponse.model_validate({**user, "authored_documents": docs})


@router.delete("/{user_id}", status_code=204, responses={404: {"description": "User not found"}})
async def delete_user(user_id: str, db: DBDep) -> None:
    """Remove a user from the knowledge graph only.

    GUARDRAIL: Graph-local. Does not affect Teamwork records.
    Tickets assigned to the user remain in the graph.
    """
    deleted = await queries.delete_user(db, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    await invalidate_cache(CACHE_KEY_EXPERTS)


@router.post(
    "/{user_id}/generate-skills",
    responses={
        404: {"description": "User not found"},
        400: {"description": "No resolved tickets found for this expert"},
    },
)
async def generate_skills(user_id: str, db: DBDep) -> GenerateSkillsResponse:
    """Use LLM to generate a skill cloud from the expert's resolved ticket history."""
    user = await queries.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    summaries = await queries.get_expert_ticket_summaries(db, user_id)
    if not summaries:
        raise HTTPException(status_code=400, detail="No resolved tickets found for this expert")
    skills = await generate_expert_skills(user.get("name") or user_id, summaries)
    await invalidate_cache(CACHE_KEY_EXPERTS)
    return GenerateSkillsResponse(skills=skills)
