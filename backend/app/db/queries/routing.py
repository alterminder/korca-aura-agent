import uuid

from neo4j import AsyncSession

from ._shared import user_uid

AURA_ROUTING_STATUSES = frozenset(
    {
        "queued",
        "running",
        "suggested",
        "no_recommendation",
        "failed",
    }
)


async def set_ticket_aura_routing_status(
    session: AsyncSession,
    ticket_id: str | int,
    status: str,
    error: str | None = None,
) -> None:
    """Persist the user-visible Aura routing lifecycle state on a ticket."""
    if status not in AURA_ROUTING_STATUSES:
        raise ValueError(f"Invalid Aura routing status: {status}")
    await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        SET t.routing_status = $status,
            t.aura_routing_error = $error,
            t.aura_routing_updated_at = toString(datetime())
        """,
        ticket_id=str(ticket_id),
        status=status,
        error=error,
    )


async def list_stale_aura_routing_tickets(
    session: AsyncSession,
    *,
    stale_minutes: int = 3,
    limit: int = 20,
) -> list[str]:
    """Return interrupted Aura jobs left in running state without a result."""
    result = await session.run(
        """
        MATCH (t:Ticket)
        WHERE t.routing_status = 'running'
          AND coalesce(t.aura_suggestion_email, '') = ''
          AND NOT exists((t)-[:HAS_ROUTING_EVENT]->(:RoutingEvent))
          AND (
            t.aura_routing_updated_at IS NULL
            OR datetime(t.aura_routing_updated_at) < datetime() - duration({minutes: $stale_minutes})
          )
        RETURN toString(t.id) AS id
        ORDER BY t.aura_routing_updated_at ASC
        LIMIT $limit
        """,
        stale_minutes=stale_minutes,
        limit=limit,
    )
    return [str(row["id"]) for row in await result.data() if row.get("id") is not None]


async def record_aura_routing_event(
    session: AsyncSession,
    ticket_id: str,
    expert_email: str | None,
    expert_name: str | None = None,
    confidence: str | None = None,
    mode: str = "manual",
    action: str = "stored",
    trace_id: str | None = None,
) -> dict:
    """Create an auditable RoutingEvent for one Aura routing attempt."""
    event_id = str(uuid.uuid4())
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        CREATE (t)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent {
            id: $event_id,
            ticket_id: $ticket_id,
            mode: $mode,
            action: $action,
            outcome: CASE
              WHEN $expert_email IS NULL THEN "upstream_error"
              WHEN assigned.email IS NULL THEN "no_ground_truth"
              WHEN toLower(assigned.email) = toLower($expert_email) THEN "correct"
              ELSE "wrong"
            END,
            aura_trace_id: $trace_id,
            suggested_email: $expert_email,
            suggested_name: $expert_name,
            confidence: $confidence,
            created_at: toString(datetime()),
            completed_at: toString(datetime())
        })
        FOREACH (_ IN CASE WHEN $expert_email IS NULL THEN [] ELSE [1] END |
            MERGE (u:User {email: $expert_email})
            ON CREATE SET u.id = $expert_uid
            SET u.name = coalesce(u.name, $expert_name)
            MERGE (e)-[:RECOMMENDED_EXPERT]->(u)
        )
        RETURN e {.*} AS event
        """,
        event_id=event_id,
        ticket_id=ticket_id,
        expert_email=expert_email,
        expert_name=expert_name,
        expert_uid=user_uid(expert_email) if expert_email else None,
        confidence=confidence,
        mode=mode,
        action=action,
        trace_id=trace_id,
    )
    record = await result.single()
    return record["event"] if record else {}


async def get_aura_routing_accuracy(session: AsyncSession) -> dict:
    """Return Aura accuracy from latest RoutingEvent per ticket vs ASSIGNED_TO."""
    result = await session.run(
        """
        MATCH (t:Ticket)-[:HAS_ROUTING_EVENT]->(e:RoutingEvent)
        MATCH (assigned:User)-[assigned_rel:ASSIGNED_TO]->(t)
        WHERE t.ingest_status = 'promoted'
          AND coalesce(assigned_rel.final, false) = true
        WITH t, assigned, e
        ORDER BY e.created_at DESC
        WITH t, assigned, collect(e)[0] AS latest_event
        WHERE latest_event.suggested_email IS NOT NULL
        RETURN
          count(t) AS evaluated,
          sum(CASE WHEN toLower(latest_event.suggested_email) = toLower(assigned.email) THEN 1 ELSE 0 END) AS correct,
          CASE
            WHEN count(t) > 0
            THEN round(100.0 * sum(CASE WHEN toLower(latest_event.suggested_email) = toLower(assigned.email) THEN 1 ELSE 0 END) / count(t), 1)
            ELSE null
          END AS accuracy_pct
        """
    )
    row = await result.single()
    if not row:
        return {"evaluated": 0, "correct": 0, "accuracy_pct": None}
    return {
        "evaluated": row["evaluated"],
        "correct": row["correct"],
        "accuracy_pct": row["accuracy_pct"],
    }


async def has_protected_assigned_to(session: AsyncSession, ticket_id: str | int) -> bool:
    """Return True when a ticket has protected historical assignment truth."""
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        MATCH (:User)-[a:ASSIGNED_TO]->(t)
        WHERE a.protected = true
          AND (
            a.source = 'historical_correction'
            OR coalesce(t.ingest_status, '') = 'promoted'
          )
        RETURN count(a) > 0 AS protected
        """,
        ticket_id=str(ticket_id),
    )
    row = await result.single()
    return bool(row and row.get("protected"))


async def has_routing_event(session: AsyncSession, ticket_id: str | int) -> bool:
    """Return True when the ticket already has at least one RoutingEvent."""
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        RETURN exists((t)-[:HAS_ROUTING_EVENT]->(:RoutingEvent)) AS has_event
        """,
        ticket_id=str(ticket_id),
    )
    row = await result.single()
    return bool(row and row.get("has_event"))


async def has_routing_recommendation(session: AsyncSession, ticket_id: str | int) -> bool:
    """Return True when Aura already produced a usable expert recommendation."""
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(event:RoutingEvent)
        WHERE event.suggested_email IS NOT NULL AND event.suggested_email <> ""
        WITH t, count(event) AS recommendation_events
        RETURN coalesce(t.aura_suggestion_email, "") <> ""
            OR recommendation_events > 0 AS has_recommendation
        """,
        ticket_id=str(ticket_id),
    )
    row = await result.single()
    return bool(row and row.get("has_recommendation"))


async def upsert_teamwork_assigned_to(
    session: AsyncSession,
    ticket_id: str,
    agent_email: str | None,
    agent_name: str | None = None,
    final: bool = False,
    protected: bool = False,
    source: str = "teamwork_sync",
) -> str:
    """Mirror Teamwork assignment into ASSIGNED_TO unless historical truth is protected."""
    agent_email = (agent_email or "").strip().lower() or None
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        OPTIONAL MATCH (:User)-[protected_rel:ASSIGNED_TO]->(t)
        WITH t, protected_rel,
             coalesce(protected_rel.protected, false) = true
             AND (
               protected_rel.source = 'historical_correction'
               OR coalesce(t.ingest_status, '') = 'promoted'
             ) AS effective_protected
        WITH t, count(CASE WHEN effective_protected THEN protected_rel END) > 0 AS has_effective_protected
        CALL (t, has_effective_protected) {
            WITH t, has_effective_protected
            WHERE has_effective_protected
            RETURN "protected" AS result
            UNION
            WITH t, has_effective_protected
            WHERE NOT has_effective_protected AND $agent_email IS NULL
            OPTIONAL MATCH (:User)-[old_rel:ASSIGNED_TO]->(t)
            WITH t, [rel IN collect(old_rel)
                     WHERE rel IS NOT NULL
                       AND NOT (
                         coalesce(rel.protected, false) = true
                         AND (
                           rel.source = 'historical_correction'
                           OR coalesce(t.ingest_status, '') = 'promoted'
                         )
                       )] AS old_rels
            FOREACH (rel IN old_rels | DELETE rel)
            RETURN "cleared" AS result
            UNION
            WITH t, has_effective_protected
            WHERE NOT has_effective_protected AND $agent_email IS NOT NULL
            OPTIONAL MATCH (:User)-[old_rel:ASSIGNED_TO]->(t)
            WITH t, [rel IN collect(old_rel)
                     WHERE rel IS NOT NULL
                       AND NOT (
                         coalesce(rel.protected, false) = true
                         AND (
                           rel.source = 'historical_correction'
                           OR coalesce(t.ingest_status, '') = 'promoted'
                         )
                       )] AS old_rels
            FOREACH (rel IN old_rels | DELETE rel)
            WITH t
            MERGE (u:User {email: $agent_email})
            ON CREATE SET u.id = $agent_uid
            SET u.name = CASE WHEN $agent_name IS NOT NULL AND $agent_name <> "" THEN $agent_name ELSE u.name END
            MERGE (u)-[a:ASSIGNED_TO]->(t)
            SET a.source = $source,
                a.protected = $protected,
                a.final = $final,
                a.assigned_at = coalesce(a.assigned_at, toString(datetime())),
                a.synced_from_teamwork_at = toString(datetime())
            RETURN "assigned" AS result
        }
        RETURN result
        """,
        ticket_id=str(ticket_id),
        agent_email=agent_email,
        agent_name=agent_name,
        agent_uid=user_uid(agent_email) if agent_email else None,
        final=final,
        protected=protected,
        source=source,
    )
    row = await result.single()
    return row["result"] if row else "missing"


async def finalize_latest_routing_event_for_ticket(
    session: AsyncSession,
    ticket_id: str,
) -> dict | None:
    """Finalize the latest RoutingEvent outcome from the current ASSIGNED_TO edge."""
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $ticket_id OR t.id = toInteger($ticket_id)
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        WITH t, head(collect(assigned)) AS assigned
        OPTIONAL MATCH (t)-[:HAS_ROUTING_EVENT]->(event:RoutingEvent)
        WITH t, assigned, event
        ORDER BY event.created_at DESC
        WITH t, assigned, head(collect(event)) AS latest_event
        WHERE latest_event IS NOT NULL
        SET latest_event.outcome = CASE
              WHEN latest_event.suggested_email IS NULL THEN "upstream_error"
              WHEN assigned.email IS NULL THEN "no_ground_truth"
              WHEN toLower(latest_event.suggested_email) = toLower(assigned.email) THEN "correct"
              ELSE "wrong"
            END,
            latest_event.completed_at = toString(datetime())
        RETURN latest_event {.*} AS event
        """,
        ticket_id=ticket_id,
    )
    row = await result.single()
    return row.get("event") if row and row.get("event") else None


async def confirm_routing(
    session: AsyncSession,
    ticket_id: str,
    expert_email: str,
    expert_name: str,
    is_override: bool = False,
) -> bool:
    """Store confirmed expert on the ticket and protect canonical assignment truth."""
    # Update ticket properties
    result = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        SET t.confirmed_expert_email = $email,
            t.confirmed_expert_name  = $name,
            t.confirmed_at           = toString(datetime()),
            t.is_override            = $is_override,
            t.routing_status         = 'confirmed'
        RETURN t
        """,
        id=ticket_id,
        email=expert_email,
        name=expert_name,
        is_override=is_override,
    )
    record = await result.single()
    if not record:
        return False

    r = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        OPTIONAL MATCH (:User)-[old_rel:ASSIGNED_TO]->(t)
        DELETE old_rel
        WITH t
        MERGE (u:User {email: $email})
        ON CREATE SET u.id = $uid, u.name = $name
        SET u.name = CASE WHEN $name <> "" THEN $name ELSE u.name END
        MERGE (u)-[a:ASSIGNED_TO]->(t)
        SET a.source = "korca",
            a.protected = true,
            a.final = true,
            a.assigned_at = toString(datetime()),
            a.is_override = $is_override
        """,
        id=ticket_id,
        email=expert_email,
        uid=user_uid(expert_email),
        name=expert_name,
        is_override=is_override,
    )
    await r.consume()
    return True


async def reassign_assigned_to(
    session: AsyncSession,
    ticket_id: str,
    expert_email: str,
    expert_name: str,
    protected: bool = True,
    final: bool = True,
) -> bool:
    """Replace the graph-local ASSIGNED_TO ground truth with a different expert.

    Used to correct test/staging assignments inside Korca only. This must not
    call Teamwork Desk; Teamwork-originated changes use upsert_teamwork_assigned_to.
    """
    r = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        OPTIONAL MATCH (prev:User)-[rel:ASSIGNED_TO]->(t)
        DELETE rel
        RETURN count(t) AS n
        """,
        id=ticket_id,
    )
    record = await r.single()
    if not record or record["n"] == 0:
        return False

    r = await session.run(
        """
        MATCH (t:Ticket) WHERE t.id = $id OR t.id = toInteger($id)
        SET t.agent_email = $email,
            t.agent_name  = $name
        WITH t
        MERGE (u:User {email: $email})
        ON CREATE SET u.id = $uid, u.name = $name
        SET u.name = CASE WHEN $name <> "" THEN $name ELSE u.name END
        MERGE (u)-[a:ASSIGNED_TO]->(t)
        SET a.source = "korca",
            a.protected = $protected,
            a.final = $final,
            a.assigned_at = toString(datetime())
        """,
        id=ticket_id,
        email=expert_email,
        uid=user_uid(expert_email),
        name=expert_name,
        protected=protected,
        final=final,
    )
    await r.consume()
    return True
