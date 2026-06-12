from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock

import pytest

from app.api.routes import aura_agents
from app.services.aura_agent import build_aura_agent_prompt, normalize_aura_agent_patch


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.aura_agents.", "")


def test_aura_agent_route_handlers_have_typed_response_models():
    assert _return_annotation_name(aura_agents.list_agents) == "list[AuraAgentResponse]"
    assert _return_annotation_name(aura_agents.get_agent) == "AuraAgentResponse"
    assert _return_annotation_name(aura_agents.patch_agent) == "AuraAgentResponse"


def test_build_aura_agent_prompt_prefixes_client_name():
    prompt = build_aura_agent_prompt("Subject: Login broken", "Acme")

    assert prompt == "Client: Acme\nSubject: Login broken"


def test_normalize_aura_agent_patch_uses_singular_dimension_for_similarity_tools():
    patch = {
        "tools": [
            {
                "name": "Semantic Ticket Finder",
                "type": "similaritySearch",
                "description": "Find similar tickets",
                "enabled": True,
                "config": {
                    "dimensions": 3072,
                    "index": "ticket_embedding_gemini",
                    "model": "gemini-embedding-001",
                    "provider": "vertexai",
                    "top_k": 9,
                },
            },
            {
                "name": "Expert Resolver",
                "type": "cypherTemplate",
                "description": "Get expert for tickets",
                "enabled": True,
                "config": {"template": "MATCH (u:User) RETURN u"},
            },
        ]
    }

    normalized = normalize_aura_agent_patch(patch)

    similarity_config = normalized["tools"][0]["config"]
    assert similarity_config["dimension"] == 3072
    assert "dimensions" not in similarity_config
    assert normalized["tools"][0]["config"]["top_k"] == 9
    assert normalized["tools"][1]["config"] == {"template": "MATCH (u:User) RETURN u"}


@pytest.mark.asyncio
async def test_list_aura_agents_returns_service_payload(client, monkeypatch):
    async def fake_list_agents():
        return [
            {
                "id": "agent-1",
                "name": "Triage Agent",
                "tools": [{"name": "Semantic Ticket Finder", "type": "similaritySearch"}],
            }
        ]

    monkeypatch.setattr("app.api.routes.aura_agents.list_aura_agents", fake_list_agents)

    resp = await client.get("/api/aura/agents")

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": "agent-1",
            "name": "Triage Agent",
            "tools": [{"name": "Semantic Ticket Finder", "type": "similaritySearch"}],
        }
    ]


@pytest.mark.asyncio
async def test_list_agents_preserves_unknown_external_fields(client, monkeypatch):
    # The response is a verbatim passthrough of the external Aura API, so unknown
    # fields must survive (extra="allow") and not be injected as nulls (exclude_none).
    monkeypatch.setattr(
        "app.api.routes.aura_agents.list_aura_agents",
        AsyncMock(
            return_value=[
                {"id": "agent-1", "name": "Triage Agent", "tools": [], "future_field": "keep-me"}
            ]
        ),
    )

    resp = await client.get("/api/aura/agents")

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["future_field"] == "keep-me"
    assert "description" not in body  # unset known field not injected as null


@pytest.mark.asyncio
async def test_get_aura_agent_returns_full_service_payload(client, monkeypatch):
    async def fake_get_agent(agent_id: str):
        return {
            "id": agent_id,
            "name": "Triage Agent",
            "system_prompt": "Route support tickets.",
            "tools": [
                {
                    "name": "Expert Resolver",
                    "type": "cypherTemplate",
                    "enabled": True,
                    "config": {"template": "MATCH (u:User) RETURN u"},
                }
            ],
        }

    monkeypatch.setattr("app.api.routes.aura_agents.get_aura_agent", fake_get_agent)

    resp = await client.get("/api/aura/agents/agent-1")

    assert resp.status_code == 200
    assert resp.json()["system_prompt"] == "Route support tickets."
    assert resp.json()["tools"][0]["config"]["template"] == "MATCH (u:User) RETURN u"


@pytest.mark.asyncio
async def test_patch_aura_agent_updates_system_prompt(client, monkeypatch):
    calls = []

    async def fake_update_agent(agent_id: str, patch: dict):
        calls.append((agent_id, patch))
        return {
            "id": agent_id,
            "name": "Triage Agent",
            "system_prompt": patch["system_prompt"],
            "tools": [],
        }

    monkeypatch.setattr("app.api.routes.aura_agents.update_aura_agent", fake_update_agent)

    resp = await client.patch(
        "/api/aura/agents/agent-1",
        json={"system_prompt": "Updated routing instructions."},
    )

    assert resp.status_code == 200
    assert calls == [("agent-1", {"system_prompt": "Updated routing instructions."})]
    assert resp.json()["system_prompt"] == "Updated routing instructions."


@pytest.mark.asyncio
async def test_patch_aura_agent_updates_tools(client, monkeypatch):
    tools = [
        {
            "name": "Semantic Ticket Finder",
            "type": "similaritySearch",
            "enabled": True,
            "config": {"top_k": 12},
        }
    ]
    calls = []

    async def fake_update_agent(agent_id: str, patch: dict):
        calls.append((agent_id, patch))
        return {
            "id": agent_id,
            "name": "Triage Agent",
            "system_prompt": "Route tickets.",
            "tools": patch["tools"],
        }

    monkeypatch.setattr("app.api.routes.aura_agents.update_aura_agent", fake_update_agent)

    resp = await client.patch("/api/aura/agents/agent-1", json={"tools": tools})

    assert resp.status_code == 200
    assert calls == [("agent-1", {"tools": tools})]
    assert resp.json()["tools"][0]["config"]["top_k"] == 12


@pytest.mark.asyncio
async def test_patch_aura_agent_updates_access_settings(client, monkeypatch):
    calls = []

    async def fake_update_agent(agent_id: str, patch: dict):
        calls.append((agent_id, patch))
        return {
            "id": agent_id,
            "name": "Triage Agent",
            "is_private": patch["is_private"],
            "is_mcp_enabled": patch["is_mcp_enabled"],
            "tools": [],
        }

    monkeypatch.setattr("app.api.routes.aura_agents.update_aura_agent", fake_update_agent)

    resp = await client.patch(
        "/api/aura/agents/agent-1",
        json={"is_private": True, "is_mcp_enabled": False},
    )

    assert resp.status_code == 200
    assert calls == [("agent-1", {"is_private": True, "is_mcp_enabled": False})]
    assert resp.json()["is_private"] is True
    assert resp.json()["is_mcp_enabled"] is False


@pytest.mark.asyncio
async def test_patch_aura_agent_requires_at_least_one_field(client):
    resp = await client.patch("/api/aura/agents/agent-1", json={})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stream_aura_agent_invocation_forwards_client_prefixed_input(client, monkeypatch):
    calls = []

    async def fake_stream_aura_agent(text: str, client_name: str, current_ticket_id: str):
        calls.append((text, client_name, current_ticket_id))
        yield b'data: {"type":"text","text":"Routing..."}\n\n'
        yield b'data: {"type":"done","status":"SUCCESS"}\n\n'

    monkeypatch.setattr("app.api.routes.aura_agents.stream_aura_agent", fake_stream_aura_agent)

    resp = await client.post(
        "/api/aura/invoke-stream",
        json={"text": "Subject: Login broken", "client_name": "Acme"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert calls == [("Subject: Login broken", "Acme", "")]
    assert '{"type":"text","text":"Routing..."}' in resp.text
