"""GatekeeperAgent — quality gate between connectors and the graph.

Every ticket and document passes through this agent before its ingest_status
is set to 'promoted'. Items that fail are staged with structured reasons and
surfaced as staged tickets for human correction.

Ticket checks (in order):
  1. content_present   — ticket has non-trivial text beyond just the subject
  2. assignee_present  — a resolver is known
  3. client_resolvable — ticket has a client domain or name we can link
  4. closed_status     — ticket is closed/resolved before it becomes routing knowledge

Document checks:
  1. content_present   — OCR extracted non-empty text
  2. expert_linked     — at least one User has an AUTHORED edge to this document
                         (checked via graph query, not here)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from neo4j import AsyncSession

from app.db.queries import set_ticket_ingest_status

logger = structlog.get_logger()

_TRIVIAL_CONTENT_THRESHOLD = 20  # characters — below this, content is too short to embed
_CLOSED_STATUSES = {"closed", "solved", "resolved"}


@dataclass
class GatekeeperResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def ingest_status(self) -> str:
        return "promoted" if self.passed else "staged"


async def gate_ticket(
    ticket: dict,
    require_assignee: bool = True,
    require_closed: bool = False,
) -> GatekeeperResult:
    """Run all quality checks on a ticket dict.

    Args:
        ticket: the ticket dict as returned by _extract_ticket() or webhook parsing.
        require_assignee: require a known assignee before promotion.
        require_closed: require closed/resolved status before promotion.
    """
    reasons: list[str] = []

    # --- Rule checks (fast, no LLM) ---

    content = (ticket.get("content") or ticket.get("preview") or "").strip()
    subject = (ticket.get("subject") or "").strip()

    if len(content) < _TRIVIAL_CONTENT_THRESHOLD and len(subject) < _TRIVIAL_CONTENT_THRESHOLD:
        reasons.append("missing_content")

    if require_assignee and not (ticket.get("agent_email") or "").strip():
        reasons.append("missing_assignee")

    # Support both nested {"client": {"domain": ..., "name": ...}} (import/webhook format)
    # and flat {"client_domain": ..., "client_name": ...} (get_ticket_full format)
    client = ticket.get("client") or {}
    client_domain = (client.get("domain") or ticket.get("client_domain") or "").strip()
    client_name = (client.get("name") or ticket.get("client_name") or "").strip()
    if not client_domain and not client_name:
        reasons.append("missing_client")

    status = (ticket.get("status") or "").strip().lower()
    if require_closed and status not in _CLOSED_STATUSES:
        reasons.append("not_closed")

    if reasons:
        notes = f"Rule checks failed: {', '.join(reasons)}"
        logger.info(
            "gatekeeper_staged",
            ticket_id=ticket.get("id"),
            reasons=reasons,
        )
        return GatekeeperResult(passed=False, reasons=reasons, notes=notes)

    logger.info("gatekeeper_promoted", ticket_id=ticket.get("id"))
    return GatekeeperResult(passed=True)


async def propose_document_experts(
    session: AsyncSession,
    document_id: str,
    topics: list[str],
    limit: int = 3,
) -> list[dict]:
    """Find experts to propose for a document based on its topics.

    Queries the graph for users who have assigned promoted tickets
    tagged with any of the document's topics. Returns ranked proposals.
    """
    if not topics:
        return []

    result = await session.run(
        """
        UNWIND $topics AS topic_name
        MATCH (tp:Topic {name: topic_name})<-[:TAGGED]-(t:Ticket)<-[:ASSIGNED_TO]-(u:User)
        WHERE t.ingest_status = 'promoted' OR t.ingest_status IS NULL
        WITH u, count(DISTINCT t) AS matching_tickets, collect(DISTINCT tp.name) AS matched_topics
        ORDER BY matching_tickets DESC
        LIMIT $limit
        RETURN u.id AS user_id, u.name AS name, u.email AS email,
               matching_tickets, matched_topics
        """,
        topics=[t.lower().strip() for t in topics if t],
        limit=limit,
    )
    rows = await result.data()
    logger.info(
        "document_experts_proposed",
        document_id=document_id,
        topics=topics,
        proposals=len(rows),
    )
    return rows


async def gate_and_persist_ticket(
    session: AsyncSession,
    ticket: dict,
    require_assignee: bool = True,
    require_closed: bool = False,
) -> GatekeeperResult:
    """Run gate_ticket() and immediately persist the result to the graph."""
    result = await gate_ticket(
        ticket,
        require_assignee=require_assignee,
        require_closed=require_closed,
    )
    await set_ticket_ingest_status(
        session,
        ticket_id=str(ticket["id"]),
        status=result.ingest_status,
        reasons=result.reasons if not result.passed else None,
        notes=result.notes if not result.passed else None,
    )
    return result
