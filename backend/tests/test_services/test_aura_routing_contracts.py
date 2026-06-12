"""Contract tests for Aura agent response parsing.

These tests pin the exact response shapes the Aura API returns so that any
change in how the agent formats its output will immediately surface here.
"""

import json
from pathlib import Path

from app.services.aura_routing import _parse_aura_expert_email

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external_payloads"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Fixture-backed external response shapes
# ---------------------------------------------------------------------------


def test_aura_output_fixture_with_recommended_prefix():
    result = _load_fixture("aura_routing_output_response.json")
    assert _parse_aura_expert_email(result) == "alice.expert@example.com"


def test_aura_content_fixture_text_block_fallback():
    result = _load_fixture("aura_routing_content_response.json")
    assert _parse_aura_expert_email(result) == "carol.expert@example.com"


def test_aura_missing_email_fixture_returns_none():
    result = _load_fixture("aura_routing_missing_email_response.json")
    assert _parse_aura_expert_email(result) is None


# ---------------------------------------------------------------------------
# Happy-path shapes
# ---------------------------------------------------------------------------


def test_output_field_with_recommended_prefix():
    result = {"output": "Based on the ticket, RECOMMENDED: alice@example.com is the best match."}
    assert _parse_aura_expert_email(result) == "alice@example.com"


def test_output_field_recommended_case_insensitive():
    result = {"output": "recommended: Bob.Smith@example.com — strong match."}
    assert _parse_aura_expert_email(result) == "bob.smith@example.com"


def test_output_field_email_without_recommended_prefix():
    # Aura agent may omit the prefix and just mention the email inline.
    result = {"output": "The ticket should go to alice@example.com based on past patterns."}
    assert _parse_aura_expert_email(result) == "alice@example.com"


def test_output_field_multiple_emails_recommended_wins():
    # When RECOMMENDED: is present it should take precedence over any earlier
    # email address that might appear in the reasoning text.
    result = {
        "output": (
            "Previously handled by old@example.com. "
            "RECOMMENDED: alice@example.com is the best match."
        )
    }
    assert _parse_aura_expert_email(result) == "alice@example.com"


def test_output_field_email_lowercased():
    result = {"output": "RECOMMENDED: Alice.Expert@EXAMPLE.COM"}
    assert _parse_aura_expert_email(result) == "alice.expert@example.com"


# ---------------------------------------------------------------------------
# content blocks fallback (Aura may return content array instead of output)
# ---------------------------------------------------------------------------


def test_content_blocks_text_type_extracted():
    result = {
        "output": "",
        "content": [
            {"type": "thinking", "text": "Let me think about this…"},
            {"type": "text", "text": "RECOMMENDED: carol@example.com is correct."},
        ],
    }
    assert _parse_aura_expert_email(result) == "carol@example.com"


def test_content_blocks_skips_thinking_block():
    result = {
        "content": [
            {"type": "thinking", "text": "The email is dave@example.com maybe"},
            {"type": "text", "text": "RECOMMENDED: carol@example.com"},
        ],
    }
    assert _parse_aura_expert_email(result) == "carol@example.com"


def test_content_blocks_only_thinking_no_text_block():
    # If there's only a thinking block with an email, it should still parse
    # the first text block — here there is none, so fall back to None.
    result = {
        "content": [
            {"type": "thinking", "text": "dave@example.com"},
        ],
    }
    assert _parse_aura_expert_email(result) is None


def test_output_field_takes_priority_over_content_blocks():
    result = {
        "output": "RECOMMENDED: primary@example.com",
        "content": [{"type": "text", "text": "RECOMMENDED: secondary@example.com"}],
    }
    assert _parse_aura_expert_email(result) == "primary@example.com"


# ---------------------------------------------------------------------------
# No-recommendation / malformed shapes
# ---------------------------------------------------------------------------


def test_output_field_no_email_returns_none():
    result = {"output": "I cannot determine the best expert for this ticket."}
    assert _parse_aura_expert_email(result) is None


def test_empty_output_and_empty_content_returns_none():
    result = {"output": ""}
    assert _parse_aura_expert_email(result) is None


def test_empty_dict_returns_none():
    assert _parse_aura_expert_email({}) is None


def test_content_empty_list_returns_none():
    result = {"output": "", "content": []}
    assert _parse_aura_expert_email(result) is None


def test_content_blocks_non_dict_entries_skipped():
    # Guard: if the content array contains non-dict items we should not crash.
    result = {
        "content": [
            "unexpected string",
            None,
            {"type": "text", "text": "RECOMMENDED: x@y.com"},
        ]
    }
    assert _parse_aura_expert_email(result) == "x@y.com"


def test_malformed_content_block_missing_text_key():
    result = {"content": [{"type": "text"}]}
    assert _parse_aura_expert_email(result) is None
