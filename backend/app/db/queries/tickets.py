import json

from neo4j import AsyncSession

from ._shared import _log_slow
from .clients import _enrich_ticket_client


async def upsert_ticket(session: AsyncSession, ticket: dict) -> None:
    """Create or update a Ticket node and its relationships."""
    # Upsert ticket node
    await session.run(
        """
        MERGE (t:Ticket {id: $id})
        SET t.subject = $subject,
            t.preview = $preview,
            t.status = $status,
            t.source = $source,
            t.source_system = $source_system,
            t.ticket_type = $ticket_type,
            t.inbox_name = $inbox_name,
            t.created_at = $created_at,
            t.resolved_at = $resolved_at,
            t.content = $content,
            t.request_content = $request_content,
            t.raw_content = $raw_content,
            t.gemini_embedding = $embedding,
            t.imported_at = toString(datetime()),
            t.ingest_status = CASE WHEN $ingest_status IS NOT NULL THEN $ingest_status ELSE coalesce(t.ingest_status, 'staged') END,
            t.staged_reasons = CASE WHEN $staged_reasons IS NOT NULL THEN $staged_reasons ELSE t.staged_reasons END,
            t.gatekeeper_notes = CASE WHEN $gatekeeper_notes IS NOT NULL THEN $gatekeeper_notes ELSE t.gatekeeper_notes END
        """,
        id=ticket["id"],
        subject=ticket["subject"],
        preview=ticket["preview"],
        status=ticket["status"],
        source=ticket.get("source", ""),
        source_system=ticket.get("source_system", ""),
        ticket_type=ticket.get("ticket_type"),
        inbox_name=ticket.get("inbox_name"),
        created_at=ticket["created_at"],
        resolved_at=ticket.get("resolved_at"),
        content=ticket.get("content", ""),
        request_content=ticket.get("request_content", ""),
        raw_content=ticket.get("raw_content", ""),
        embedding=ticket.get("embedding"),
        ingest_status=ticket.get("ingest_status"),
        staged_reasons=ticket.get("staged_reasons"),
        gatekeeper_notes=ticket.get("gatekeeper_notes"),
    )

    # Link client company (FROM) — no PII, only company name + domain
    client = ticket.get("client")
    if client:
        # Use domain as merge key if available, otherwise name
        merge_key = client["domain"] if client.get("domain") else client.get("name", "")
        if merge_key:
            await session.run(
                """
                MERGE (c:Client {domain: $domain})
                SET c.name = CASE WHEN $name <> '' THEN $name ELSE c.name END
                WITH c
                MATCH (t:Ticket {id: $ticket_id})
                MERGE (t)-[:FROM]->(c)
                """,
                domain=client.get("domain") or merge_key,
                name=client.get("name", ""),
                ticket_id=ticket["id"],
            )

    # Link topics via TAGGED — batch all tags in one round-trip
    tags = [tag.lower().strip() for tag in (ticket.get("tags") or []) if tag.strip()]
    if tags:
        await session.run(
            """
            UNWIND $tags AS name
            MERGE (tp:Topic {name: name})
            WITH tp
            MATCH (t:Ticket {id: $ticket_id})
            MERGE (t)-[:TAGGED]->(tp)
            """,
            tags=tags,
            ticket_id=ticket["id"],
        )


async def get_teamwork_filter_options(session: AsyncSession) -> dict:
    """Return distinct client names, agent names, and inbox names for Teamwork tickets."""
    result = await session.run(
        """
        MATCH (t:Ticket {source_system: 'teamwork'})
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        OPTIONAL MATCH (t)-[:FROM]->(c:Client)
        WITH t, head(collect(assigned)) AS agent, c
        RETURN
            collect(DISTINCT CASE WHEN c.name IS NOT NULL AND c.name <> '' THEN c.name ELSE c.domain END) AS clients,
            collect(DISTINCT agent.name) AS agents,
            collect(DISTINCT t.inbox_name) AS inboxes
        """
    )
    record = await result.single()
    if not record:
        return {"clients": [], "agents": [], "inboxes": []}
    return {
        "clients": sorted([v for v in record["clients"] if v]),
        "agents": sorted([v for v in record["agents"] if v]),
        "inboxes": sorted([v for v in record["inboxes"] if v]),
    }


def _ticket_filter_clause(
    source_system: str | None = None,
    client_filter: str = "",
    agent_filter: str = "",
    inbox_filter: str = "",
    search: str = "",
    mismatch_only: bool = False,
    unrouted_only: bool = False,
    imported_after: str = "",
) -> tuple[str, str, dict]:
    where = "WHERE t.source_system = $source_system" if source_system else "WHERE true"

    first_clause = f"""
        {where}
          AND ($inbox_filter = '' OR toLower(coalesce(t.inbox_name, '')) CONTAINS toLower($inbox_filter))
          AND ($search = '' OR toLower(coalesce(t.subject, '')) CONTAINS toLower($search))
          AND ($imported_after = '' OR coalesce(t.imported_at, '') >= $imported_after)
    """

    second_clause = """
        WHERE ($client_filter = '' OR (c IS NOT NULL AND (
                toLower(coalesce(c.name, '')) CONTAINS toLower($client_filter) OR
                toLower(coalesce(c.domain, '')) CONTAINS toLower($client_filter) OR
                toLower(coalesce(parent.name, '')) CONTAINS toLower($client_filter) OR
                toLower(coalesce(parent.domain, '')) CONTAINS toLower($client_filter))))
          AND ($agent_filter = '' OR (assigned IS NOT NULL AND (
                toLower(coalesce(assigned.name, '')) CONTAINS toLower($agent_filter) OR
                toLower(coalesce(assigned.email, '')) CONTAINS toLower($agent_filter))))
          AND (NOT $mismatch_only OR is_mismatch)
          AND (NOT $unrouted_only OR t.routing_status IS NULL OR t.routing_status = 'unrouted')
    """

    params = {
        "source_system": source_system or "",
        "client_filter": client_filter,
        "agent_filter": agent_filter,
        "inbox_filter": inbox_filter,
        "search": search,
        "mismatch_only": mismatch_only,
        "unrouted_only": unrouted_only,
        "imported_after": imported_after,
    }
    return first_clause, second_clause, params


@_log_slow
async def list_tickets(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 20,
    source_system: str | None = None,
    client_filter: str = "",
    agent_filter: str = "",
    inbox_filter: str = "",
    search: str = "",
    mismatch_only: bool = False,
    unrouted_only: bool = False,
    sort_by_status: bool = False,
    imported_after: str = "",
) -> list[dict]:
    first_clause, second_clause, params = _ticket_filter_clause(
        source_system=source_system,
        client_filter=client_filter,
        agent_filter=agent_filter,
        inbox_filter=inbox_filter,
        search=search,
        mismatch_only=mismatch_only,
        unrouted_only=unrouted_only,
        imported_after=imported_after,
    )
    result = await session.run(
        f"""
        MATCH (t:Ticket)
        {first_clause}
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(event:RoutingEvent)
        WITH t, assigned, event
        ORDER BY event.created_at DESC
        WITH t, assigned, head(collect(event)) AS latest_event
        OPTIONAL MATCH (routed:User)-[:ROUTED_TO]->(t)
        WITH t, assigned, latest_event, head(collect(routed)) AS routed
        OPTIONAL MATCH (t)-[:FROM]->(c:Client)
        OPTIONAL MATCH (c)-[:WORKS_FOR]->(parent:Client)
        OPTIONAL MATCH (t)-[:TAGGED]->(tp:Topic)
        WITH t, assigned, latest_event, routed, c, parent, collect(tp.name) AS tags,
             CASE
               WHEN latest_event.suggested_email IS NOT NULL
                 AND assigned.email IS NOT NULL
                 AND latest_event.suggested_email <> assigned.email
               THEN true
               ELSE false
             END AS is_mismatch
        {second_clause}
        RETURN t {{
            .id, .subject, .preview, .status, .source, .source_system, .imported_at,
            .ticket_type, .inbox_name, .created_at, .resolved_at,
            .routing_status, .aura_routing_error, .teamwork_action_error, .confirmed_expert_name,
            .aura_suggestion_email, .aura_suggestion_confidence,
            .ingest_status, .staged_reasons, .gatekeeper_notes,
            request_preview: substring(coalesce(t.request_content, t.preview, ''), 0, 500),
            tags: tags,
            agent_name: assigned.name,
            agent_email: assigned.email,
            assigned_to_name: assigned.name,
            assigned_to_email: assigned.email,
            routed_to_name: routed.name,
            routed_to_email: routed.email,
            latest_routing_event_id: latest_event.id,
            latest_routing_event_outcome: latest_event.outcome,
            latest_aura_suggestion_email: latest_event.suggested_email,
            latest_aura_suggestion_name: latest_event.suggested_name,
            is_mismatch: is_mismatch,
            client_name: c.name,
            client_domain: c.domain
        }} AS ticket
        ORDER BY
          CASE WHEN $sort_by_status
            THEN CASE WHEN toLower(coalesce(t.status, '')) IN ['closed', 'solved', 'resolved'] THEN 1 ELSE 0 END
            ELSE 0
          END ASC,
          t.created_at DESC
        SKIP $offset LIMIT $limit
        """,
        offset=offset,
        limit=limit,
        sort_by_status=sort_by_status,
        **params,
    )
    records = await result.data()
    return [_enrich_ticket_client(r["ticket"]) for r in records]


async def get_ticket_processing_payload(session: AsyncSession, ticket_id: str | int) -> dict | None:
    """Return stored request processing fields used to avoid duplicate LLM work."""
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        RETURN t.request_content AS request_content,
               t.content AS content,
               t.raw_content AS raw_content,
               t.gemini_embedding AS gemini_embedding,
               t.ticket_type AS ticket_type,
               t.inbox_name AS inbox_name
        """,
        ticket_id=str(ticket_id),
    )
    row = await result.single()
    return dict(row) if row else None


async def count_tickets_filtered(
    session: AsyncSession,
    source_system: str | None = None,
    client_filter: str = "",
    agent_filter: str = "",
    inbox_filter: str = "",
    search: str = "",
    mismatch_only: bool = False,
    unrouted_only: bool = False,
    imported_after: str = "",
) -> int:
    """Return total count matching the same filters as list_tickets."""
    first_clause, second_clause, params = _ticket_filter_clause(
        source_system=source_system,
        client_filter=client_filter,
        agent_filter=agent_filter,
        inbox_filter=inbox_filter,
        search=search,
        mismatch_only=mismatch_only,
        unrouted_only=unrouted_only,
        imported_after=imported_after,
    )
    result = await session.run(
        f"""
        MATCH (t:Ticket)
        {first_clause}
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(event:RoutingEvent)
        WITH t, assigned, event
        ORDER BY event.created_at DESC
        WITH t, assigned, head(collect(event)) AS latest_event
        OPTIONAL MATCH (t)-[:FROM]->(c:Client)
        OPTIONAL MATCH (c)-[:WORKS_FOR]->(parent:Client)
        WITH t, assigned, latest_event, c, parent,
             CASE
               WHEN latest_event.suggested_email IS NOT NULL
                 AND assigned.email IS NOT NULL
                 AND latest_event.suggested_email <> assigned.email
               THEN true
               ELSE false
             END AS is_mismatch
        {second_clause}
        RETURN count(t) AS n
        """,
        **params,
    )
    record = await result.single()
    return record["n"] if record else 0


async def delete_tickets_by_source(session: AsyncSession, source_system: str) -> int:
    count_result = await session.run(
        "MATCH (t:Ticket {source_system: $source_system}) RETURN count(t) AS n",
        source_system=source_system,
    )
    record = await count_result.single()
    n = record["n"] if record else 0
    await session.run(
        """
        MATCH (t:Ticket {source_system: $source_system})
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        DETACH DELETE t, e
        """,
        source_system=source_system,
    )
    await session.run("MATCH (b:BlockedTicket) DELETE b")
    return n


async def ticket_exists(session: AsyncSession, ticket_id: int) -> bool:
    result = await session.run(
        "MATCH (t:Ticket {id: $id}) RETURN t LIMIT 1",
        id=ticket_id,
    )
    return await result.single() is not None


async def count_tickets(session: AsyncSession, source_system: str | None = None) -> int:
    if source_system:
        result = await session.run(
            "MATCH (t:Ticket) WHERE t.source_system = $source_system RETURN count(t) AS n",
            source_system=source_system,
        )
    else:
        result = await session.run("MATCH (t:Ticket) RETURN count(t) AS n")
    record = await result.single()
    return record["n"] if record else 0


async def get_latest_ticket_timestamp(session: AsyncSession, source_system: str) -> str | None:
    """Return the most recent created_at ISO string for tickets from a given source.

    Teamwork uses this as a createdAt floor for created-only imports.
    """
    result = await session.run(
        """
        MATCH (t:Ticket)
        WHERE t.source_system = $source_system AND t.created_at IS NOT NULL
        RETURN t.created_at AS ts
        ORDER BY t.created_at DESC
        LIMIT 1
        """,
        source_system=source_system,
    )
    record = await result.single()
    return record["ts"] if record else None


async def get_ticket_full(session: AsyncSession, ticket_id: str) -> dict | None:
    # Teamwork IDs are stored as integers. toInteger() returns null for non-numeric
    # strings, so the OR is safe for historical string IDs.
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(event:RoutingEvent)
        WITH t, assigned, event
        ORDER BY event.created_at DESC
        WITH t, assigned, head(collect(event)) AS latest_event
        OPTIONAL MATCH (routed:User)-[:ROUTED_TO]->(t)
        OPTIONAL MATCH (t)-[:FROM]->(c:Client)
        OPTIONAL MATCH (t)-[:TAGGED]->(tp:Topic)
        WITH t, assigned, routed, latest_event, c, collect(tp.name) AS tags
        RETURN t {
            .id, .subject, .preview, .status, .source, .source_system,
            .ticket_type, .inbox_name, .created_at, .resolved_at, .content, .request_content, .raw_content,
            .gemini_embedding,
            .routing_status, .aura_routing_error, .teamwork_action_error, .routing_suggestions, .routed_at,
            .confirmed_expert_email, .confirmed_expert_name, .confirmed_at, .is_override,
            .aura_suggestion_email, .aura_suggestion_confidence,
            .ingest_status, .staged_reasons, .gatekeeper_notes,
            tags: tags,
            agent_name: assigned.name,
            agent_email: assigned.email,
            assigned_to_name: assigned.name,
            assigned_to_email: assigned.email,
            routed_to_name: routed.name,
            routed_to_email: routed.email,
            latest_routing_event_id: latest_event.id,
            latest_routing_event_outcome: latest_event.outcome,
            latest_aura_suggestion_email: latest_event.suggested_email,
            latest_aura_suggestion_name: latest_event.suggested_name,
            client_name: c.name,
            client_domain: c.domain
        } AS ticket
        """,
        id=ticket_id,
    )
    record = await result.single()
    if not record:
        return None
    ticket = _enrich_ticket_client(record["ticket"])
    # Convert any Neo4j temporal types to ISO strings (routed_at, confirmed_at)
    for field in ("routed_at", "confirmed_at", "created_at", "resolved_at"):
        v = ticket.get(field)
        if v is not None and hasattr(v, "iso_format"):
            ticket[field] = v.iso_format()
    # Parse stored JSON suggestions back to list
    if ticket.get("routing_suggestions"):
        try:
            ticket["routing_suggestions"] = json.loads(ticket["routing_suggestions"])
        except Exception:
            ticket["routing_suggestions"] = []
    return ticket


async def set_ticket_ingest_status(
    session: AsyncSession,
    ticket_id: str,
    status: str,
    reasons: list[str] | None = None,
    notes: str | None = None,
) -> None:
    """Set ingest_status on a Ticket node. Called by GatekeeperAgent after evaluation."""
    await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        SET t.ingest_status = $status,
            t.staged_reasons = CASE WHEN $reasons IS NOT NULL THEN $reasons ELSE t.staged_reasons END,
            t.gatekeeper_notes = CASE WHEN $notes IS NOT NULL THEN $notes ELSE t.gatekeeper_notes END,
            t.gated_at = toString(datetime())
        """,
        id=ticket_id,
        status=status,
        reasons=reasons,
        notes=notes,
    )


async def list_staged_tickets(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 50,
) -> list[dict]:
    """Return tickets with ingest_status = 'staged', newest first."""
    result = await session.run(
        """
        MATCH (t:Ticket {ingest_status: 'staged'})
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        OPTIONAL MATCH (t)-[:FROM]->(c:Client)
        OPTIONAL MATCH (t)-[:TAGGED]->(tp:Topic)
        WITH t, assigned, c, collect(tp.name) AS tags
        RETURN t {
            .id, .subject, .preview, .status, .source_system,
            .created_at, .ingest_status, .staged_reasons, .gatekeeper_notes, .gated_at,
            .routing_status, .routing_suggestions,
            tags: tags,
            agent_name: assigned.name,
            agent_email: assigned.email,
            client_name: c.name,
            client_domain: c.domain
        } AS ticket
        ORDER BY t.created_at DESC
        SKIP $offset LIMIT $limit
        """,
        offset=offset,
        limit=limit,
    )
    records = await result.data()
    return [_enrich_ticket_client(r["ticket"]) for r in records]


async def count_staged_tickets(session: AsyncSession) -> int:
    result = await session.run("MATCH (t:Ticket {ingest_status: 'staged'}) RETURN count(t) AS n")
    record = await result.single()
    return record["n"] if record else 0


async def _resolve_ticket_id(session: AsyncSession, ticket_id: str) -> str | None:
    result = await session.run(
        "MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id) RETURN t.id AS real_id",
        id=ticket_id,
    )
    record = await result.single()
    return record["real_id"] if record else None


async def _purge_ticket(session: AsyncSession, real_id: str) -> None:
    """Delete the ticket node, its RoutingEvent nodes, and all relationships."""
    await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        DETACH DELETE t, e
        """,
        id=real_id,
    )


async def delete_ticket(session: AsyncSession, ticket_id: str) -> bool:
    """Remove a ticket and its routing events. Does not blocklist — it may be re-imported."""
    real_id = await _resolve_ticket_id(session, ticket_id)
    if real_id is None:
        return False
    await _purge_ticket(session, real_id)
    return True


async def spam_ticket(session: AsyncSession, ticket_id: str) -> bool:
    """Remove a ticket and blocklist its ID so it is never re-imported."""
    real_id = await _resolve_ticket_id(session, ticket_id)
    if real_id is None:
        return False
    await _purge_ticket(session, real_id)
    await session.run("MERGE (:BlockedTicket {id: $id})", id=real_id)
    return True


async def bulk_delete_tickets(session: AsyncSession, ticket_ids: list[str]) -> int:
    """Delete multiple tickets and add them to the blocklist."""
    deleted = 0
    for ticket_id in ticket_ids:
        if await spam_ticket(session, ticket_id):
            deleted += 1
    return deleted


async def is_ticket_blocked(session: AsyncSession, ticket_id: str | int) -> bool:
    result = await session.run(
        "MATCH (b:BlockedTicket) WHERE b.id = $id OR b.id = toInteger($id) RETURN count(b) AS n",
        id=str(ticket_id),
    )
    record = await result.single()
    return bool(record and record["n"] > 0)
