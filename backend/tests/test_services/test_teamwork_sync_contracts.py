"""Contract tests for Teamwork API response parsing.

These tests pin the exact shapes returned by the Teamwork Desk v2 API so that
any payload drift (e.g. threadType changing from string to dict) surfaces here
rather than silently corrupting imported tickets.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.services.teamwork import _normalize_ticket
from app.services.teamwork_sync import (
    _extract_ticket,
    _handle_blocked_status,
    _is_blocked_subject,
    _qualifies_for_embedding,
    _summarize_and_embed_ticket,
    run_full_teamwork_import,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external_payloads"


async def _async_value(value):
    await asyncio.sleep(0)
    return value


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Helpers — representative Teamwork payload fragments
# ---------------------------------------------------------------------------


def _raw(overrides: dict | None = None) -> dict:
    """Minimal ticket from the /tickets.json list endpoint."""
    base = {
        "id": 4093106,
        "subject": "Website font is broken",
        "preview": "The font is missing on the homepage.",
        "status": "active",
        "source": "email",
        "createdAt": "2026-05-10T09:00:00Z",
        "assignedTo": {
            "email": "alice@example.com",
            "firstName": "Alice",
            "lastName": "Expert",
        },
        "company": {"name": "Acme Ltd"},
        "customer": {"email": "user@acme.com"},
        "tags": [{"name": "billing"}, {"name": "urgent"}],
    }
    if overrides:
        base.update(overrides)
    return base


def _detail(overrides: dict | None = None) -> dict:
    """Minimal ticket detail from the /tickets/{id}.json endpoint."""
    base = {
        "id": 4093106,
        "type": "Question",
        "inboxName": "Support",
        "fields": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _thread(body: str, thread_type: str | dict = "message", thread_id: int = 1) -> dict:
    return {"id": thread_id, "body": body, "threadType": thread_type}


# ---------------------------------------------------------------------------
# Fixture-backed Teamwork v2 API shapes
# ---------------------------------------------------------------------------


def test_teamwork_v2_included_relationship_fixture_normalizes_ticket():
    payload = _load_fixture("teamwork_ticket_page_with_included.json")
    normalized = _normalize_ticket(payload["data"][0], payload["included"])

    assert normalized["id"] == 4093106
    assert normalized["subject"] == "Website font is broken"
    assert normalized["preview"] == "The font is missing on the homepage."
    assert normalized["status"] == "active"
    assert normalized["customer"]["email"] == "requester@acme.com"
    assert normalized["company"]["name"] == "Acme Ltd"
    assert normalized["assignedTo"]["email"] == "alice@example.com"
    assert normalized["type"] == "Question"
    assert normalized["inboxName"] == "Support"
    assert [tag["name"] for tag in normalized["tags"]] == ["billing", "urgent"]
    assert normalized["threads"][0]["body"] == "<p>Font is gone from the homepage.</p>"
    assert normalized["threads"][0]["threadType"] == "message"
    assert normalized["threads"][1]["threadType"] == "note"


def test_teamwork_v2_fixture_feeds_sync_extraction_without_losing_request_body():
    payload = _load_fixture("teamwork_ticket_page_with_included.json")
    normalized = _normalize_ticket(payload["data"][0], payload["included"])
    ticket = _extract_ticket(normalized, normalized, normalized["threads"])

    assert ticket["agent_email"] == "alice@example.com"
    assert ticket["agent_name"] == "Alice Expert"
    assert ticket["client"] == {"name": "Acme Ltd", "domain": "acme.com"}
    assert ticket["tags"] == ["billing", "urgent"]
    assert ticket["content"].startswith("Website font is broken")
    assert "Font is gone from the homepage." in ticket["content"]
    assert "Internal note should not be request content." not in ticket["content"]
    assert "Internal note should not be request content." not in ticket["raw_content"]


def test_teamwork_v2_malformed_relationship_fixture_degrades_without_crashing():
    payload = _load_fixture("teamwork_ticket_detail_missing_relationships.json")
    normalized = _normalize_ticket(payload["ticket"], payload["included"])
    ticket = _extract_ticket(normalized, normalized, normalized["threads"])

    assert normalized["customer"] == {}
    assert normalized["threads"] == []
    assert ticket["content"] == (
        "Malformed relationship payload\n\nCustomer cannot access the portal."
    )
    assert ticket["agent_email"] is None
    assert ticket["client"] is None


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


def test_extract_ticket_returns_expected_fields():
    ticket = _extract_ticket(_raw(), _detail(), [_thread("<p>Font is gone.</p>")])

    assert ticket["id"] == 4093106
    assert ticket["subject"] == "Website font is broken"
    assert ticket["status"] == "active"
    assert ticket["source_system"] == "teamwork"
    assert ticket["ticket_type"] == "Question"
    assert ticket["inbox_name"] == "Support"
    assert ticket["agent_email"] == "alice@example.com"
    assert ticket["agent_name"] == "Alice Expert"


def test_extract_ticket_content_strips_html_from_first_thread():
    ticket = _extract_ticket(
        _raw(),
        _detail(),
        [_thread("<p>Hello <b>world</b>.</p>")],
    )
    assert "Hello world." in ticket["content"]
    assert "<p>" not in ticket["content"]
    assert "<b>" not in ticket["content"]


# ---------------------------------------------------------------------------
# threadType variations
# ---------------------------------------------------------------------------


def test_extract_ticket_thread_type_as_string():
    threads = [_thread("Customer message.", thread_type="message")]
    ticket = _extract_ticket(_raw(), _detail(), threads)
    assert "Customer message." in ticket["content"]


def test_extract_ticket_thread_type_as_dict_with_name():
    # Teamwork sometimes wraps threadType as {"name": "message"}
    threads = [_thread("Customer message.", thread_type={"name": "message"})]
    ticket = _extract_ticket(_raw(), _detail(), threads)
    assert "Customer message." in ticket["content"]


def test_extract_ticket_system_threads_excluded_from_content():
    # "forward", "automation", "status", "note" threads should not appear in content
    threads = [
        _thread("Auto-reply: ticket received.", thread_type="automation", thread_id=1),
        _thread("Status changed to active.", thread_type="status", thread_id=2),
        _thread("Customer's actual request.", thread_type="message", thread_id=3),
    ]
    ticket = _extract_ticket(_raw(), _detail(), threads)
    assert "Customer's actual request." in ticket["content"]
    assert "Auto-reply" not in ticket["content"]
    assert "Status changed" not in ticket["content"]


def test_extract_ticket_only_first_non_system_thread_in_content():
    # content is subject + first message only; raw_content includes all threads
    threads = [
        _thread("First message.", thread_type="message", thread_id=1),
        _thread("Reply from agent.", thread_type="message", thread_id=2),
    ]
    ticket = _extract_ticket(_raw(), _detail(), threads)
    assert "First message." in ticket["content"]
    assert "Reply from agent." not in ticket["content"]
    assert "Reply from agent." in ticket["raw_content"]


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def test_extract_ticket_tags_as_list_of_dicts():
    raw = _raw({"tags": [{"name": "billing"}, {"name": "urgent"}]})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["tags"] == ["billing", "urgent"]


def test_extract_ticket_tags_as_list_of_strings():
    raw = _raw({"tags": ["billing", "urgent"]})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["tags"] == ["billing", "urgent"]


def test_extract_ticket_empty_tags():
    raw = _raw({"tags": []})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["tags"] == []


# ---------------------------------------------------------------------------
# assignedTo variations
# ---------------------------------------------------------------------------


def test_extract_ticket_missing_assigned_to():
    raw = _raw({"assignedTo": None})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["agent_email"] is None
    assert ticket["agent_name"] == ""


@pytest.mark.asyncio
async def test_run_full_teamwork_import_skips_blocked_status_and_reports_progress(monkeypatch):
    progress_updates = []
    cache_invalidations = []

    async def fake_get_latest_ticket_timestamp(_session, source_system: str):
        await _async_value(None)
        assert source_system == "teamwork"

    async def fake_fetch_all_tickets(*, created_after):
        assert created_after is None
        return await _async_value(
            [
                {
                    "id": 7987868,
                    "subject": "Sales pitch",
                    "preview": "Unwanted request",
                    "status": "Spam",
                    "createdAt": "2026-06-06T18:55:00Z",
                }
            ]
        )

    async def fake_get_sync_state(_session):
        return await _async_value({"cursor": "2026-06-06T18:00:00Z"})

    async def fake_progress(**kwargs):
        await _async_value(None)
        progress_updates.append(kwargs)

    async def fake_invalidate_cache(*keys):
        await _async_value(None)
        cache_invalidations.append(keys)

    class _FakeDbContext:
        async def __aenter__(self):
            return await _async_value(object())

        async def __aexit__(self, exc_type, exc, tb):
            return await _async_value(False)

    monkeypatch.setattr("app.services.teamwork_sync.db_context", _FakeDbContext)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_latest_ticket_timestamp",
        fake_get_latest_ticket_timestamp,
    )
    monkeypatch.setattr("app.services.teamwork_sync.tw.fetch_all_tickets", fake_fetch_all_tickets)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_teamwork_update_sync_state",
        fake_get_sync_state,
    )
    monkeypatch.setattr("app.services.teamwork_sync.invalidate_cache", fake_invalidate_cache)

    result = await run_full_teamwork_import(set_progress=fake_progress)

    assert result == {
        "created_after": None,
        "initial_import": True,
        "imported": 0,
        "skipped": 1,
        "failed": 0,
        "total": 1,
    }
    assert progress_updates[-1] == {
        "status": "running",
        "message": "Processed 1/1",
        "processed": 1,
        "imported": 0,
        "skipped": 1,
        "failed": 0,
        "total": 1,
        "started_at": progress_updates[0]["started_at"],
    }
    assert cache_invalidations == [("korca:cache:filter_options", "korca:cache:experts")]


@pytest.mark.asyncio
async def test_run_full_teamwork_import_marks_continuation_as_initial_without_sync_cursor(
    monkeypatch,
):
    bootstrap_calls = []

    async def fake_get_latest_ticket_timestamp(_session, source_system: str):
        await _async_value(None)
        assert source_system == "teamwork"
        return "2026-06-06T18:55:00Z"

    async def fake_fetch_all_tickets(*, created_after):
        await _async_value(None)
        assert created_after == "2026-06-06T18:55:00Z"
        return []

    async def fake_get_sync_state(_session):
        return await _async_value(None)

    async def fake_bootstrap(_session):
        await _async_value(None)
        bootstrap_calls.append("bootstrap")

    async def fake_progress(**_kwargs):
        await _async_value(None)

    async def fake_invalidate_cache(*_keys):
        await _async_value(None)

    class _FakeDbContext:
        async def __aenter__(self):
            return await _async_value(object())

        async def __aexit__(self, exc_type, exc, tb):
            return await _async_value(False)

    monkeypatch.setattr("app.services.teamwork_sync.db_context", _FakeDbContext)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_latest_ticket_timestamp",
        fake_get_latest_ticket_timestamp,
    )
    monkeypatch.setattr("app.services.teamwork_sync.tw.fetch_all_tickets", fake_fetch_all_tickets)
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.get_teamwork_update_sync_state",
        fake_get_sync_state,
    )
    monkeypatch.setattr(
        "app.services.teamwork_sync.queries.bootstrap_teamwork_update_sync_state",
        fake_bootstrap,
    )
    monkeypatch.setattr("app.services.teamwork_sync.invalidate_cache", fake_invalidate_cache)

    result = await run_full_teamwork_import(set_progress=fake_progress)

    assert result["created_after"] == "2026-06-06T18:55:00Z"
    assert result["initial_import"] is True
    assert bootstrap_calls == ["bootstrap"]


def test_extract_ticket_assigned_to_missing_last_name():
    raw = _raw({"assignedTo": {"email": "bob@example.com", "firstName": "Bob", "lastName": ""}})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["agent_email"] == "bob@example.com"
    assert ticket["agent_name"] == "Bob"


# ---------------------------------------------------------------------------
# Client extraction
# ---------------------------------------------------------------------------


def test_extract_client_from_company_name():
    raw = _raw({"company": {"name": "Acme Ltd"}, "customer": {"email": "user@acme.com"}})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["client"]["name"] == "Acme Ltd"
    assert ticket["client"]["domain"] == "acme.com"


def test_extract_client_prefers_custom_field_over_company():
    detail = _detail(
        {
            "fields": [
                {"agentLabel": "Customer Name", "textValue": "Custom Corp"},
            ]
        }
    )
    raw = _raw({"company": {"name": "Should Be Ignored"}, "customer": {"email": "x@custom.com"}})
    ticket = _extract_ticket(raw, detail, [])
    assert ticket["client"]["name"] == "Custom Corp"


def test_extract_client_unconfigured_personal_domain_is_treated_as_client(monkeypatch):
    monkeypatch.setattr(settings, "teamwork_personal_domains", [])
    raw = _raw({"company": {}, "customer": {"email": "user@gmail.com"}})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["client"] is not None
    assert ticket["client"]["domain"] == "gmail.com"
    assert ticket["client"]["name"] == ""


def test_extract_client_business_domain_without_company_name():
    raw = _raw({"company": {}, "customer": {"email": "user@businesscorp.com"}})
    ticket = _extract_ticket(raw, _detail(), [])
    assert ticket["client"] is not None
    assert ticket["client"]["domain"] == "businesscorp.com"
    assert ticket["client"]["name"] == ""


def test_extract_client_personal_domain_excluded(monkeypatch):
    monkeypatch.setattr(settings, "teamwork_personal_domains", ["partnerco.com"])
    raw = _raw({"company": {}, "customer": {"email": "user@partnerco.com"}})
    ticket = _extract_ticket(raw, _detail(), [])
    # configured personal domain -> not treated as a client org
    assert ticket["client"] is None


def test_is_blocked_subject_empty_blocklist_blocks_nothing(monkeypatch):
    monkeypatch.setattr(settings, "teamwork_subject_blocklist", [])
    assert not _is_blocked_subject("Job: board failure notification")


def test_is_blocked_subject_matches_configured_prefix(monkeypatch):
    monkeypatch.setattr(settings, "teamwork_subject_blocklist", ["job: "])
    assert _is_blocked_subject("Job: board failure")  # case-insensitive
    assert not _is_blocked_subject("Invoice #42")


@pytest.mark.asyncio
async def test_handle_blocked_status_matches_teamwork_display_case():
    assert await _handle_blocked_status({"status": "Spam", "subject": "Sales pitch"}, 4093106)
    assert await _handle_blocked_status({"status": " Deleted ", "subject": "Removed"}, 4093107)
    assert await _handle_blocked_status({"status": "merged", "subject": "Duplicate"}, 4093108)
    assert not await _handle_blocked_status(
        {"status": "Waiting on customer", "subject": "Real request"},
        4093109,
    )


# ---------------------------------------------------------------------------
# Embedding gate — only closed/assigned/client tickets enter the vector index
# ---------------------------------------------------------------------------


def _embeddable_ticket(overrides: dict | None = None) -> dict:
    base = {
        "id": 4093106,
        "subject": "Website font is broken",
        "status": "closed",
        "agent_email": "alice@example.com",
        "client": {"name": "Acme Ltd", "domain": "acme.com"},
        "content": "Website font is broken\n\nFont is gone from the homepage.",
    }
    if overrides:
        base.update(overrides)
    return base


def test_qualifies_for_embedding_requires_closed_assignee_and_client():
    assert _qualifies_for_embedding(_embeddable_ticket())
    assert _qualifies_for_embedding(_embeddable_ticket({"status": "Resolved"}))
    assert _qualifies_for_embedding(_embeddable_ticket({"client": {"name": "", "domain": "a.com"}}))

    assert not _qualifies_for_embedding(_embeddable_ticket({"status": "active"}))
    assert not _qualifies_for_embedding(_embeddable_ticket({"status": "Waiting on customer"}))
    assert not _qualifies_for_embedding(_embeddable_ticket({"agent_email": None}))
    assert not _qualifies_for_embedding(_embeddable_ticket({"agent_email": "  "}))
    assert not _qualifies_for_embedding(_embeddable_ticket({"client": None}))
    assert not _qualifies_for_embedding(_embeddable_ticket({"client": {"name": "", "domain": ""}}))


@pytest.mark.asyncio
async def test_summarize_and_embed_processes_qualifying_ticket(monkeypatch):
    summarize = AsyncMock(return_value="Clean summary")
    embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    monkeypatch.setattr("app.services.teamwork_sync.summarize_ticket", summarize)
    monkeypatch.setattr("app.services.teamwork_sync.embed_query", embed)

    ticket = _embeddable_ticket()
    assert await _summarize_and_embed_ticket(ticket, ticket["id"]) is True

    assert ticket["request_content"] == "Website font is broken\n\nFont is gone from the homepage."
    assert ticket["content"] == "Clean summary"
    assert ticket["embedding"] == [0.1, 0.2, 0.3]
    summarize.assert_awaited_once()
    embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_and_embed_skips_llm_for_non_qualifying_ticket(monkeypatch):
    summarize = AsyncMock(side_effect=AssertionError("Open tickets must not be summarized"))
    embed = AsyncMock(side_effect=AssertionError("Open tickets must not be embedded"))
    monkeypatch.setattr("app.services.teamwork_sync.summarize_ticket", summarize)
    monkeypatch.setattr("app.services.teamwork_sync.embed_query", embed)

    ticket = _embeddable_ticket({"status": "active"})
    # True — the caller must still persist, stage, and route the ticket
    assert await _summarize_and_embed_ticket(ticket, ticket["id"]) is True

    assert ticket["request_content"] == "Website font is broken\n\nFont is gone from the homepage."
    assert ticket["content"] == "Website font is broken\n\nFont is gone from the homepage."
    assert ticket["embedding"] is None


@pytest.mark.asyncio
async def test_summarize_and_embed_returns_false_for_empty_request_body():
    ticket = _embeddable_ticket({"content": "   "})
    assert await _summarize_and_embed_ticket(ticket, ticket["id"]) is False


# ---------------------------------------------------------------------------
# Preview fallback when no threads exist
# ---------------------------------------------------------------------------


def test_extract_ticket_content_falls_back_to_preview_when_no_threads():
    # The preview fallback reads from ticket_detail, not from raw.
    ticket = _extract_ticket(_raw(), _detail({"preview": "Short preview text."}), [])
    assert "Short preview text." in ticket["content"]


def test_extract_ticket_preview_not_used_when_threads_present():
    detail = _detail({"preview": "Should not appear."})
    ticket = _extract_ticket(_raw(), detail, [_thread("Real message body.")])
    assert "Should not appear." not in ticket["content"]
    assert "Real message body." in ticket["content"]
