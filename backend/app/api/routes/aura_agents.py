from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.aura_agent import (
    get_aura_agent,
    list_aura_agents,
    stream_aura_agent,
    update_aura_agent,
)

router = APIRouter()
logger = structlog.get_logger()


class AuraAgentPatch(BaseModel):
    system_prompt: str | None = Field(default=None, min_length=1)
    tools: list[dict[str, Any]] | None = None
    is_private: bool | None = None
    is_mcp_enabled: bool | None = None

    @model_validator(mode="after")
    def require_update_field(self) -> "AuraAgentPatch":
        if (
            self.system_prompt is None
            and self.tools is None
            and self.is_private is None
            and self.is_mcp_enabled is None
        ):
            raise ValueError("system_prompt, tools, is_private, or is_mcp_enabled is required")
        return self


class AuraInvokeRequest(BaseModel):
    text: str = Field(min_length=1)
    client_name: str = ""
    current_ticket_id: str = ""


class AuraAgentToolResponse(BaseModel):
    # Aura API tool object — keep unknown fields (extra="allow").
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    type: str | None = None
    description: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class AuraAgentResponse(BaseModel):
    """Compatible with the frontend `AuraAgent` type. Proxies the external Neo4j
    Aura agent API, lightly normalized for the frontend: unknown upstream fields
    are preserved (`extra="allow"`), `null` fields are dropped (the routes set
    `response_model_exclude_none`), and `tools` always serializes as a list so the
    UI can map over it. Known fields stay optional."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    description: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    dbid: str | None = None
    enabled: bool | None = None
    is_private: bool | None = None
    is_mcp_enabled: bool | None = None
    endpoint_link: str | None = None
    mcp_endpoint_link: str | None = None
    system_prompt: str | None = None
    tools: list[AuraAgentToolResponse] = Field(default_factory=list)


@router.get(
    "/agents",
    response_model_exclude_none=True,
    responses={502: {"description": "Aura API error"}},
)
async def list_agents() -> list[AuraAgentResponse]:
    try:
        agents = await list_aura_agents()
    except httpx.HTTPStatusError as exc:
        logger.warning("aura_agents_list_error", status_code=exc.response.status_code)
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc.response.text}") from exc
    except Exception as exc:
        logger.warning("aura_agents_list_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc}") from exc
    return [AuraAgentResponse.model_validate(agent) for agent in agents]


@router.post("/invoke-stream", responses={502: {"description": "Aura API error"}})
async def invoke_agent_stream(body: AuraInvokeRequest) -> StreamingResponse:
    try:
        return StreamingResponse(
            stream_aura_agent(body.text, body.client_name, body.current_ticket_id),
            media_type="text/event-stream",
        )
    except Exception as exc:
        logger.warning("aura_agent_stream_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc}") from exc


@router.get(
    "/agents/{agent_id}",
    response_model_exclude_none=True,
    responses={502: {"description": "Aura API error"}},
)
async def get_agent(agent_id: str) -> AuraAgentResponse:
    try:
        agent = await get_aura_agent(agent_id)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "aura_agent_get_error",
            agent_id=agent_id,
            status_code=exc.response.status_code,
        )
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc.response.text}") from exc
    except Exception as exc:
        logger.warning("aura_agent_get_error", agent_id=agent_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc}") from exc
    return AuraAgentResponse.model_validate(agent)


@router.patch(
    "/agents/{agent_id}",
    response_model_exclude_none=True,
    responses={502: {"description": "Aura API error"}},
)
async def patch_agent(agent_id: str, body: AuraAgentPatch) -> AuraAgentResponse:
    try:
        agent = await update_aura_agent(agent_id, body.model_dump(exclude_none=True))
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "aura_agent_patch_error",
            agent_id=agent_id,
            status_code=exc.response.status_code,
        )
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc.response.text}") from exc
    except Exception as exc:
        logger.warning("aura_agent_patch_error", agent_id=agent_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Aura API error: {exc}") from exc
    return AuraAgentResponse.model_validate(agent)
