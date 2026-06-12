"""Neo4j Aura Agent client for hackathon demo routing.

Calls the Aura-hosted triage agent via REST API.
Bearer tokens are cached in memory for up to 55 minutes (tokens expire at 60).
"""

import time
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import structlog

from app.config import settings
from app.services._http import get_aura_client

logger = structlog.get_logger()

_TOKEN_URL = "https://api.neo4j.io/oauth/token"

# Cached token state
_cached_token: str | None = None
_token_expires_at: float = 0.0


async def _get_bearer_token() -> str:
    global _cached_token, _token_expires_at

    if _cached_token and time.monotonic() < _token_expires_at:
        return _cached_token

    async with get_aura_client() as client:
        resp = await client.post(
            _TOKEN_URL,
            auth=(settings.aura_client_id, settings.aura_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

    _cached_token = data["access_token"]
    # Cache for 55 minutes (tokens expire at 60)
    _token_expires_at = time.monotonic() + 55 * 60
    logger.info("aura_token_refreshed")
    return _cached_token


def _agent_url() -> str:
    """Return the base URL for the single configured Aura agent (without /invoke)."""
    endpoint = settings.aura_agent_endpoint.rstrip("/")
    if not endpoint:
        raise ValueError("AURA_AGENT_ENDPOINT is not configured")
    if "/agents/" not in endpoint:
        raise ValueError("AURA_AGENT_ENDPOINT must include /agents/{agent_id}/invoke")

    parts = urlsplit(endpoint)
    if parts.scheme != "https" or parts.netloc != "api.neo4j.io":
        raise ValueError("AURA_AGENT_ENDPOINT must point to https://api.neo4j.io")

    # Strip /invoke suffix — the /agents collection endpoint returns HTTP 500 on Neo4j's side
    return endpoint.rsplit("/invoke", 1)[0]


async def _aura_api_get(url: str) -> dict | list:
    token = await _get_bearer_token()
    async with get_aura_client() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


async def _aura_api_patch(url: str, patch: dict) -> dict:
    token = await _get_bearer_token()
    async with get_aura_client() as client:
        resp = await client.patch(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=patch,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


def _normalize_aura_tool_for_update(tool: dict) -> dict:
    """Return a copy of a tool using the public Aura API update schema."""
    normalized_tool = {**tool}
    config = tool.get("config")
    if not isinstance(config, dict):
        return normalized_tool

    normalized_config = {**config}
    if tool.get("type") == "similaritySearch" and "dimensions" in normalized_config:
        normalized_config.setdefault("dimension", normalized_config["dimensions"])
        normalized_config.pop("dimensions", None)

    normalized_tool["config"] = normalized_config
    return normalized_tool


def normalize_aura_agent_patch(patch: dict) -> dict:
    """Normalize PATCH payloads before forwarding them to Aura.

    Aura PATCH is shallow for the tools array: if provided, it replaces all tools.
    Keep the frontend convenient while ensuring the outgoing payload matches the
    public API schema for fields that Aura may return in a different shape.
    """
    normalized_patch = {**patch}
    tools = patch.get("tools")
    if isinstance(tools, list):
        normalized_patch["tools"] = [
            _normalize_aura_tool_for_update(tool) if isinstance(tool, dict) else tool
            for tool in tools
        ]
    return normalized_patch


async def list_aura_agents() -> list[dict]:
    """Return the single configured Aura agent as a one-item list.

    The /agents collection endpoint returns HTTP 500 on Neo4j's side, so we
    fetch the specific agent directly and wrap it.
    """
    result = await _aura_api_get(_agent_url())
    if not isinstance(result, dict):
        raise ValueError("Aura agent response was not an object")
    return [result]


async def get_aura_agent(agent_id: str) -> dict:
    """Return a full Aura agent definition, including prompt and tools."""
    result = await _aura_api_get(_agent_url())
    if not isinstance(result, dict):
        raise ValueError("Aura agent response was not an object")
    return result


async def update_aura_agent(agent_id: str, patch: dict) -> dict:
    """Partially update an Aura agent definition."""
    result = await _aura_api_patch(
        _agent_url(),
        normalize_aura_agent_patch(patch),
    )
    if not isinstance(result, dict):
        raise ValueError("Aura agent update response was not an object")
    return result


def build_aura_agent_prompt(
    text: str,
    client_name: str = "",
    current_ticket_id: str = "",
) -> str:
    client = client_name.strip()
    body = text.strip()
    ticket_id = current_ticket_id.strip()
    metadata = []
    if ticket_id:
        metadata.append(f"Current ticket ID: {ticket_id}")
    if client:
        metadata.append(f"Client: {client}")
    return "\n".join([*metadata, body]) if metadata else body


async def stream_aura_agent(
    text: str,
    client_name: str = "",
    current_ticket_id: str = "",
) -> AsyncIterator[bytes]:
    """Invoke the configured Aura agent and yield its SSE response."""
    if not settings.aura_agent_endpoint:
        raise ValueError("AURA_AGENT_ENDPOINT is not configured")

    token = await _get_bearer_token()
    prompt = build_aura_agent_prompt(text, client_name, current_ticket_id)

    async with (
        get_aura_client() as client,
        client.stream(
            "POST",
            settings.aura_agent_endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"input": prompt, "stream": True},
            timeout=180.0,
        ) as resp,
    ):
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes():
            yield chunk


async def route_with_aura_agent(
    subject: str,
    content: str,
    client_name: str = "",
    current_ticket_id: str = "",
) -> dict:
    """Send a ticket to the Aura agent and return its routing recommendation.

    Returns the raw JSON response from the agent. The 'output' field contains
    the agent's text recommendation.
    """
    if not settings.aura_agent_endpoint:
        raise ValueError("AURA_AGENT_ENDPOINT is not configured")

    token = await _get_bearer_token()

    ticket_text = f"{subject}\n\n{content[:2000]}" if content.strip() else subject
    prompt = build_aura_agent_prompt(ticket_text, client_name, current_ticket_id)

    async with get_aura_client() as client:
        resp = await client.post(
            settings.aura_agent_endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"input": prompt},
            timeout=60.0,
        )
        resp.raise_for_status()

    result = resp.json()
    # Extract text block for logging
    _output_text = result.get("output", "")
    if not _output_text:
        for _block in result.get("content", []):
            if isinstance(_block, dict) and _block.get("type") == "text":
                _output_text = _block.get("text", "")
                break
    logger.info(
        "aura_agent_response",
        subject=subject[:60],
        client_name=client_name or "(none)",
        keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__,
        agent_output=_output_text[:1000],
    )
    return result
