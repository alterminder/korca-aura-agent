import sys

import pytest

from app.services.gatekeeper import gate_ticket


@pytest.mark.asyncio
async def test_gate_ticket_uses_rule_checks_without_importing_mistral(monkeypatch):
    warnings = []

    class _BlockedMistral:
        def __getattr__(self, name):
            raise AssertionError("gatekeeper should not import or call Mistral")

    def fake_warning(*args, **kwargs):
        warnings.append((args, kwargs))

    monkeypatch.setitem(sys.modules, "mistralai", _BlockedMistral())
    monkeypatch.setitem(sys.modules, "mistralai.client", _BlockedMistral())
    monkeypatch.setattr("app.services.gatekeeper.logger.warning", fake_warning)

    result = await gate_ticket(
        {
            "id": "123",
            "subject": "Login issue for customer",
            "content": "Customer cannot log into the site and needs help with password reset.",
            "status": "closed",
            "agent_email": "expert@example.com",
            "client": {"name": "Acme", "domain": "acme.test"},
        },
        require_assignee=True,
        require_closed=True,
    )

    assert result.passed is True
    assert result.reasons == []
    assert warnings == []


@pytest.mark.asyncio
async def test_gate_ticket_stages_missing_required_fields():
    result = await gate_ticket(
        {
            "id": "123",
            "subject": "Hi",
            "content": "",
            "status": "active",
            "agent_email": "",
            "client": {},
        },
        require_assignee=True,
        require_closed=True,
    )

    assert result.passed is False
    assert result.reasons == [
        "missing_content",
        "missing_assignee",
        "missing_client",
        "not_closed",
    ]


@pytest.mark.asyncio
async def test_gate_ticket_stages_open_ticket_even_when_assigned():
    result = await gate_ticket(
        {
            "id": "4093106",
            "subject": "Website font",
            "content": "Customer reports an issue with the website font.",
            "status": "Waiting on customer",
            "agent_email": "expert@example.com",
            "client": {"name": "Example Education", "domain": "example-education.org"},
        },
        require_assignee=True,
        require_closed=True,
    )

    assert result.passed is False
    assert result.reasons == ["not_closed"]


@pytest.mark.asyncio
async def test_gate_ticket_stages_closed_unassigned_ticket():
    result = await gate_ticket(
        {
            "id": "4093106",
            "subject": "Website font",
            "content": "Customer reports an issue with the website font.",
            "status": "closed",
            "agent_email": "",
            "client": {"name": "Example Education", "domain": "example-education.org"},
        },
        require_assignee=True,
        require_closed=True,
    )

    assert result.passed is False
    assert result.reasons == ["missing_assignee"]
