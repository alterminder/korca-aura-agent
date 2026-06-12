"""Teamwork Desk API v2 client with conservative rate limiting."""

from __future__ import annotations

import asyncio
import http
import json
import time
from urllib.parse import urlparse

import httpx
import structlog
from redis.asyncio import Redis

from app.config import settings

logger = structlog.get_logger()

PAGE_SIZE = 500
_LOW_RATE_LIMIT_THRESHOLD = 20
INCLUDES = "customers,companies,messages,users,tags,inboxes,ticketstatuses,tickettypes"

# Stay safely under 120 req/min: 80 req/min = 0.75s between requests.
_MIN_INTERVAL = 0.75
_TEAMWORK_RATE_KEY = "korca:teamwork_rate_slot"


async def _rate_limit() -> None:
    """Distributed rate limit across all processes.

    Allows one Teamwork request per _MIN_INTERVAL seconds.
    """
    async with Redis.from_url(settings.redis_url, decode_responses=True) as r:
        while True:
            acquired = await r.set(_TEAMWORK_RATE_KEY, "1", nx=True, px=int(_MIN_INTERVAL * 1000))
            if acquired:
                return
            await asyncio.sleep(0.05)


async def _request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """HTTP request with rate limiting and automatic 429 retry."""
    while True:
        await _rate_limit()
        resp = await client.request(method, url, **kwargs)

        if resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS:
            reset_ts = resp.headers.get("X-Rate-Limit-Reset")
            remaining = resp.headers.get("X-Rate-Limit-Remaining", "0")
            wait = max(0.0, float(reset_ts) - time.time()) + 1.0 if reset_ts else 60.0
            logger.warning("Rate limited by Teamwork", wait_seconds=wait, remaining=remaining)
            await asyncio.sleep(wait)
            continue

        remaining = resp.headers.get("X-Rate-Limit-Remaining")
        if remaining and int(remaining) < _LOW_RATE_LIMIT_THRESHOLD:
            logger.warning("Teamwork rate limit running low", remaining=remaining)

        resp.raise_for_status()
        return resp


def _teamwork_host() -> str:
    configured = settings.teamwork_subdomain.strip()
    if not configured:
        raise ValueError("TEAMWORK_SUBDOMAIN is required")
    parsed = urlparse(configured if "://" in configured else f"https://{configured}")
    return parsed.netloc.strip("/")


def _base_url() -> str:
    return f"https://{_teamwork_host()}/desk/api/v2"


def _client() -> httpx.AsyncClient:
    if not settings.teamwork_api_key:
        raise ValueError("TEAMWORK_API_KEY is required for Teamwork Desk API v2")
    return httpx.AsyncClient(
        base_url=_base_url(),
        headers={
            "Authorization": f"Bearer {settings.teamwork_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def fetch_all_tickets(created_after: str | None = None) -> list[dict]:
    """Fetch only newly-created Teamwork tickets when created_after is provided.

    Existing tickets are intentionally not update-synced from the bulk import path.
    Single-ticket reimport remains the explicit refresh path for changed tickets.
    """
    tickets: list[dict] = []
    page = 1
    base_params: dict = {
        "pageSize": PAGE_SIZE,
        "includes": INCLUDES,
        "orderBy": "createdAt",
        "orderMode": "asc",
    }
    if created_after:
        base_params["filter"] = json.dumps({"createdAt": {"$gt": created_after}})
        logger.info("Incremental Teamwork v2 created-ticket fetch", created_after=created_after)
    else:
        logger.info("Full Teamwork v2 fetch")

    async with _client() as client:
        while True:
            resp = await _request(
                client, "GET", "/tickets.json", params={**base_params, "page": page}
            )
            data = resp.json()
            batch = data.get("tickets") or data.get("data") or []
            included = data.get("included") or {}
            tickets.extend([_normalize_ticket(ticket, included) for ticket in batch])

            logger.info("Fetched Teamwork ticket page", page=page, count=len(batch))

            if _is_last_page(data, page, len(batch)):
                break
            page += 1

    return tickets


async def fetch_updated_tickets(updated_after: str) -> list[dict]:
    """Fetch Teamwork tickets changed after the live-sync cursor."""
    tickets: list[dict] = []
    page = 1
    base_params: dict = {
        "pageSize": PAGE_SIZE,
        "includes": INCLUDES,
        "orderBy": "updatedAt",
        "orderMode": "asc",
        "filter": json.dumps({"updatedAt": {"$gt": updated_after}}),
    }
    logger.info("Incremental Teamwork v2 updated-ticket fetch", updated_after=updated_after)

    async with _client() as client:
        while True:
            resp = await _request(
                client, "GET", "/tickets.json", params={**base_params, "page": page}
            )
            data = resp.json()
            batch = data.get("tickets") or data.get("data") or []
            included = data.get("included") or {}
            tickets.extend([_normalize_ticket(ticket, included) for ticket in batch])

            logger.info("Fetched Teamwork updated-ticket page", page=page, count=len(batch))

            if _is_last_page(data, page, len(batch)):
                break
            page += 1

    return tickets


async def fetch_ticket_threads(ticket_id: int) -> list[dict]:
    """Fetch messages for one ticket through the v2 ticket include payload."""
    ticket = await fetch_ticket_full(ticket_id)
    return ticket.get("threads") or []


async def fetch_ticket_full(ticket_id: int) -> dict:
    """Fetch one ticket with related data through Teamwork Desk API v2."""
    async with _client() as client:
        try:
            resp = await _request(
                client,
                "GET",
                f"/tickets/{ticket_id}.json",
                params={"includes": INCLUDES},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == http.HTTPStatus.NOT_FOUND:
                return {}
            raise
        data = resp.json()
        included = data.get("included") or {}
        ticket = data.get("ticket") or data.get("tickets") or data.get("data") or {}
        if isinstance(ticket, list):
            ticket = ticket[0] if ticket else {}
        return _normalize_ticket(ticket, included) if ticket else {}


async def fetch_agents() -> list[dict]:
    """Fetch all Desk users through v2."""
    async with _client() as client:
        try:
            resp = await _request(client, "GET", "/users.json", params={"pageSize": PAGE_SIZE})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == http.HTTPStatus.NOT_FOUND:
                return []
            raise
        data = resp.json()
        return data.get("users") or data.get("data") or []


def _find_agent_by_email(agents: list[dict], expert_email: str) -> dict | None:
    return next(
        (
            candidate
            for candidate in agents
            if str(candidate.get("email") or "").lower() == expert_email.lower()
        ),
        None,
    )


def _agent_display_name(agent: dict, fallback_email: str) -> str:
    first = str(agent.get("firstName") or "").strip()
    last = str(agent.get("lastName") or "").strip()
    full_name = " ".join(part for part in (first, last) if part)
    return full_name or str(agent.get("name") or "").strip() or fallback_email


async def post_private_note(
    ticket_id: int,
    message: str,
    mention_email: str | None = None,
    mention_name: str | None = None,
) -> dict:
    """Post an internal Teamwork note. Teamwork v2 expects threadType as "note"."""
    payload: dict[str, object] = {
        "message": message,
        "threadType": "note",
    }
    async with _client() as client:
        if mention_email:
            users_resp = await _request(
                client, "GET", "/users.json", params={"pageSize": PAGE_SIZE}
            )
            users_data = users_resp.json()
            agents = users_data.get("users") or users_data.get("data") or []
            agent = _find_agent_by_email(agents, mention_email)
            if not agent or not agent.get("id"):
                raise ValueError(f"Teamwork agent not found for {mention_email}")

            display_name = (mention_name or "").strip() or _agent_display_name(agent, mention_email)
            payload["message"] = (
                message if message.lstrip().startswith("@") else f"@{display_name} {message}"
            )
            payload["mentions"] = [{"id": agent["id"], "type": "users"}]

        resp = await _request(client, "POST", f"/tickets/{ticket_id}/messages.json", json=payload)
        return resp.json()


async def assign_ticket_to_expert(ticket_id: int, expert_email: str) -> dict:
    """Assign a Teamwork ticket to a Desk agent found by email."""
    async with _client() as client:
        users_resp = await _request(client, "GET", "/users.json", params={"pageSize": PAGE_SIZE})
        users_data = users_resp.json()
        agents = users_data.get("users") or users_data.get("data") or []
        agent = _find_agent_by_email(agents, expert_email)
        if not agent or not agent.get("id"):
            raise ValueError(f"Teamwork agent not found for {expert_email}")

        payload = {
            "ticket": {
                "agent": {"id": agent["id"]},
            },
        }
        resp = await _request(client, "PATCH", f"/tickets/{ticket_id}.json", json=payload)
        return resp.json()


def _is_last_page(data: dict, page: int, batch_size: int) -> bool:
    max_pages = data.get("maxPages") or data.get("pages")
    if max_pages is not None:
        return page >= int(max_pages)
    meta = data.get("meta") or {}
    page_meta = meta.get("page", {})
    if "hasMore" in page_meta:
        return page_meta.get("hasMore") is False
    if page_meta.get("pages") is not None:
        return page >= int(page_meta["pages"])
    if batch_size == 0:
        return True
    return batch_size < PAGE_SIZE


def _normalize_ticket(ticket: dict, included: dict) -> dict:
    customer = _related(ticket, included, "customer", "customers", "contact", "contacts")
    company = _related(ticket, included, "company", "companies")
    assigned = _related(ticket, included, "agent", "assignedTo", "user", "users")
    inbox = _related(ticket, included, "inbox", "inboxes")
    ticket_type = _related(ticket, included, "type", "ticketType", "tickettypes")
    status = _related(ticket, included, "status", "ticketStatus", "ticketstatuses")
    tags = _related_list(ticket, included, "tags")
    messages = _messages(ticket, included)

    normalized = {
        **ticket,
        "id": ticket.get("id"),
        "subject": ticket.get("subject", ""),
        "preview": ticket.get("preview") or ticket.get("previewText") or "",
        "status": _name_or_value(status) or ticket.get("state") or ticket.get("status") or "active",
        "source": (
            _name_or_value(_related(ticket, included, "source", "ticketsources"))
            or _name_or_value(ticket.get("source"))
        ),
        "customer": customer or ticket.get("customer") or {},
        "company": company or ticket.get("company") or {},
        "assignedTo": assigned or ticket.get("assignedTo") or {},
        "tags": tags or ticket.get("tags") or [],
        "type": _name_or_value(ticket_type) or _name_or_value(ticket.get("type")),
        "inboxName": _name_or_value(inbox) or _name_or_value(ticket.get("inboxName")),
        "createdAt": ticket.get("createdAt") or ticket.get("created_at"),
        "updatedAt": ticket.get("updatedAt") or ticket.get("updated_at"),
        "threads": messages,
    }
    return normalized


def _messages(ticket: dict, included: dict) -> list[dict]:
    direct = ticket.get("messages") or ticket.get("threads") or []
    messages = direct if isinstance(direct, list) else []
    if messages:
        messages = [
            _included_by_id(included, message.get("type") or "messages", message.get("id"))
            or _included_by_id(included, "messages", message.get("id"))
            or message
            for message in messages
        ]
    if not messages:
        messages = _related_list(ticket, included, "messages")
    if not messages:
        ticket_id = str(ticket.get("id"))
        messages = [
            message
            for message in _as_list(included.get("messages"))
            if str(message.get("ticketId") or message.get("ticket_id") or "") == ticket_id
            or str((message.get("ticket") or {}).get("id") or "") == ticket_id
        ]
    return [_normalize_message(message) for message in messages]


def _normalize_message(message: dict) -> dict:
    meta = message.get("meta") or {}
    return {
        **message,
        "id": message.get("id"),
        "type": message.get("type") or message.get("messageType") or message.get("kind") or "",
        "threadType": message.get("threadType") or meta.get("threadType"),
        "body": (
            message.get("body")
            or message.get("htmlBody")
            or message.get("textBody")
            or message.get("content")
            or ""
        ),
        "textBody": message.get("textBody") or message.get("plainText") or "",
        "createdAt": message.get("createdAt") or message.get("created_at"),
    }


def _related(ticket: dict, included: dict, *names: str) -> dict:
    for name in names:
        direct = ticket.get(name)
        if isinstance(direct, dict):
            found = _included_by_id(included, direct.get("type") or name, direct.get("id"))
            return found or direct
        if isinstance(direct, int | str):
            found = _included_by_id(included, name, direct)
            if found:
                return found

        rel = (ticket.get("relationships") or {}).get(name) or {}
        rel_data = rel.get("data") if isinstance(rel, dict) else None
        if isinstance(rel_data, dict):
            found = _included_by_id(included, rel_data.get("type") or name, rel_data.get("id"))
            if found:
                return found
        elif isinstance(rel_data, int | str):
            found = _included_by_id(included, name, rel_data)
            if found:
                return found
    return {}


def _related_list(ticket: dict, included: dict, name: str) -> list[dict]:
    direct = ticket.get(name)
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]

    rel = (ticket.get("relationships") or {}).get(name) or {}
    rel_data = rel.get("data") if isinstance(rel, dict) else None
    if isinstance(rel_data, list):
        found = []
        for item in rel_data:
            if isinstance(item, dict):
                match = _included_by_id(included, item.get("type") or name, item.get("id"))
                if match:
                    found.append(match)
        return found
    return []


def _included_by_id(included: dict, collection: str, item_id: int | str | None) -> dict:
    if item_id is None:
        return {}
    candidates = _as_list(included.get(collection)) or _as_list(included.get(f"{collection}s"))
    for item in candidates:
        if str(item.get("id")) == str(item_id):
            return item
    return {}


def _as_list(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _name_or_value(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or value.get("label") or "")
    return str(value or "")
