import json
import os
from typing import ClassVar

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from app.services import teamwork


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.status_code = 200
        self.headers = {"X-Rate-Limit-Remaining": "100"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _FakeAsyncClient:
    instances: ClassVar[list["_FakeAsyncClient"]] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self.patch_calls: list[dict] = []
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def request(self, method: str, url: str, **kwargs):
        m = method.upper()
        if m == "GET":
            return await self._get(url, params=kwargs.get("params"))
        if m == "POST":
            return await self._post(url, json=kwargs.get("json"))
        if m == "PATCH":
            return await self._patch(url, json=kwargs.get("json"))
        raise NotImplementedError(method)

    async def _get(self, url: str, params: dict | None = None):
        self.get_calls.append({"url": url, "params": params or {}})
        return _FakeResponse(
            {
                "tickets": [
                    {
                        "id": 123,
                        "subject": "New ticket",
                        "previewText": "Preview",
                        "createdAt": "2026-05-10T12:00:00Z",
                        "state": "active",
                        "customer": {"email": "person@example.com"},
                        "company": {"name": "Example Ltd"},
                        "messages": [
                            {"id": 1, "type": "message", "body": "<p>Hello</p>"},
                        ],
                    }
                ],
                "maxPages": 1,
            }
        )

    async def _post(self, url: str, json: dict | None = None):
        self.post_calls.append({"url": url, "json": json or {}})
        return _FakeResponse({"ok": True})

    async def _patch(self, url: str, json: dict | None = None):
        self.patch_calls.append({"url": url, "json": json or {}})
        return _FakeResponse({"ok": True})


def test_teamwork_base_url_normalizes_host(monkeypatch):
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "https://acme.eu.teamwork.com/")

    assert teamwork._base_url() == "https://acme.eu.teamwork.com/desk/api/v2"


def test_normalize_ticket_resolves_included_message_bodies():
    normalized = teamwork._normalize_ticket(
        {
            "id": 4093106,
            "subject": "Website font",
            "messages": [
                {"id": 1, "type": "messages", "meta": {"threadType": "Message"}},
                {"id": 2, "type": "messages", "meta": {"threadType": "Note"}},
            ],
        },
        {
            "messages": [
                {
                    "id": 1,
                    "htmlBody": "<p>The font is missing.</p>",
                    "textBody": "The font is missing.",
                    "threadType": "message",
                    "ticket": {"id": 4093106, "type": "tickets"},
                },
                {
                    "id": 2,
                    "htmlBody": "Korca Aura suggests Expert.",
                    "textBody": "Korca Aura suggests Expert.",
                    "threadType": "note",
                    "ticket": {"id": 4093106, "type": "tickets"},
                },
            ]
        },
    )

    assert normalized["threads"][0]["body"] == "<p>The font is missing.</p>"
    assert normalized["threads"][0]["threadType"] == "message"
    assert normalized["threads"][1]["body"] == "Korca Aura suggests Expert."
    assert normalized["threads"][1]["threadType"] == "note"


def test_is_last_page_respects_teamwork_meta_has_more_when_page_size_is_capped():
    data = {
        "meta": {
            "page": {
                "count": 1466,
                "pageSize": 100,
                "pageOffset": 0,
                "pages": 15,
                "hasMore": True,
            }
        }
    }

    assert not teamwork._is_last_page(data, page=1, batch_size=100)


@pytest.mark.asyncio
async def test_fetch_all_tickets_uses_v2_bearer_and_created_at_filter(monkeypatch):
    async def no_rate_limit() -> None:
        return None

    _FakeAsyncClient.instances = []
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "acme.eu.teamwork.com")
    monkeypatch.setattr(teamwork.settings, "teamwork_api_key", "v2-key")
    monkeypatch.setattr(teamwork.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(teamwork, "_rate_limit", no_rate_limit)

    tickets = await teamwork.fetch_all_tickets(created_after="2026-05-01T00:00:00Z")

    client = _FakeAsyncClient.instances[0]
    assert client.kwargs["base_url"] == "https://acme.eu.teamwork.com/desk/api/v2"
    assert client.kwargs["headers"]["Authorization"] == "Bearer v2-key"
    params = client.get_calls[0]["params"]
    assert client.get_calls[0]["url"] == "/tickets.json"
    assert "updatedAt" not in params.get("filter", "")
    assert json.loads(params["filter"]) == {"createdAt": {"$gt": "2026-05-01T00:00:00Z"}}
    assert tickets[0]["id"] == 123
    assert tickets[0]["preview"] == "Preview"
    assert tickets[0]["customer"]["email"] == "person@example.com"
    assert tickets[0]["company"]["name"] == "Example Ltd"
    assert tickets[0]["threads"][0]["body"] == "<p>Hello</p>"


@pytest.mark.asyncio
async def test_fetch_updated_tickets_uses_updated_at_cursor(monkeypatch):
    async def no_rate_limit() -> None:
        return None

    _FakeAsyncClient.instances = []
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "acme.eu.teamwork.com")
    monkeypatch.setattr(teamwork.settings, "teamwork_api_key", "v2-key")
    monkeypatch.setattr(teamwork.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(teamwork, "_rate_limit", no_rate_limit)

    tickets = await teamwork.fetch_updated_tickets(updated_after="2026-05-21T10:00:00Z")

    client = _FakeAsyncClient.instances[0]
    params = client.get_calls[0]["params"]
    assert client.get_calls[0]["url"] == "/tickets.json"
    assert params["orderBy"] == "updatedAt"
    assert params["orderMode"] == "asc"
    assert json.loads(params["filter"]) == {"updatedAt": {"$gt": "2026-05-21T10:00:00Z"}}
    assert tickets[0]["updatedAt"] is None


@pytest.mark.asyncio
async def test_post_private_note_uses_thread_type_note(monkeypatch):
    async def no_rate_limit() -> None:
        return None

    _FakeAsyncClient.instances = []
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "acme.eu.teamwork.com")
    monkeypatch.setattr(teamwork.settings, "teamwork_api_key", "v2-key")
    monkeypatch.setattr(teamwork.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(teamwork, "_rate_limit", no_rate_limit)

    await teamwork.post_private_note(ticket_id=123, message="Korca Aura suggests Example Expert.")

    client = _FakeAsyncClient.instances[0]
    assert client.post_calls == [
        {
            "url": "/tickets/123/messages.json",
            "json": {
                "message": "Korca Aura suggests Example Expert.",
                "threadType": "note",
            },
        }
    ]


@pytest.mark.asyncio
async def test_post_private_note_can_mention_agent_by_email(monkeypatch):
    async def no_rate_limit() -> None:
        return None

    class _MentionClient(_FakeAsyncClient):
        async def _get(self, url: str, params: dict | None = None):
            self.get_calls.append({"url": url, "params": params or {}})
            return _FakeResponse(
                {
                    "users": [
                        {
                            "id": 42,
                            "email": "expert@example.com",
                            "firstName": "Example",
                            "lastName": "Expert",
                        },
                    ]
                }
            )

    _MentionClient.instances = []
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "acme.eu.teamwork.com")
    monkeypatch.setattr(teamwork.settings, "teamwork_api_key", "v2-key")
    monkeypatch.setattr(teamwork.httpx, "AsyncClient", _MentionClient)
    monkeypatch.setattr(teamwork, "_rate_limit", no_rate_limit)

    await teamwork.post_private_note(
        ticket_id=123,
        message="Korca Aura suggests Example Expert.",
        mention_email="expert@example.com",
        mention_name="Example Expert",
    )

    client = _MentionClient.instances[0]
    assert client.get_calls[0]["url"] == "/users.json"
    assert client.post_calls == [
        {
            "url": "/tickets/123/messages.json",
            "json": {
                "message": "@Example Expert Korca Aura suggests Example Expert.",
                "threadType": "note",
                "mentions": [{"id": 42, "type": "users"}],
            },
        }
    ]


@pytest.mark.asyncio
async def test_assign_ticket_to_expert_looks_up_agent_id_and_patches_ticket(monkeypatch):
    async def no_rate_limit() -> None:
        return None

    class _AssignClient(_FakeAsyncClient):
        async def _get(self, url: str, params: dict | None = None):
            self.get_calls.append({"url": url, "params": params or {}})
            return _FakeResponse(
                {
                    "users": [
                        {
                            "id": 42,
                            "email": "expert@example.com",
                            "firstName": "Example",
                            "lastName": "Expert",
                        },
                    ]
                }
            )

    _AssignClient.instances = []
    monkeypatch.setattr(teamwork.settings, "teamwork_subdomain", "acme.eu.teamwork.com")
    monkeypatch.setattr(teamwork.settings, "teamwork_api_key", "v2-key")
    monkeypatch.setattr(teamwork.httpx, "AsyncClient", _AssignClient)
    monkeypatch.setattr(teamwork, "_rate_limit", no_rate_limit)

    await teamwork.assign_ticket_to_expert(ticket_id=123, expert_email="expert@example.com")

    client = _AssignClient.instances[0]
    assert client.get_calls[0]["url"] == "/users.json"
    assert client.patch_calls == [
        {
            "url": "/tickets/123.json",
            "json": {
                "ticket": {
                    "agent": {"id": 42},
                },
            },
        }
    ]
