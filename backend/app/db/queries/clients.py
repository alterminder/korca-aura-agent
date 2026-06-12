from neo4j import AsyncSession

from ._shared import _log_slow


def _segment_domain_name(domain: str) -> str:
    """Turn a domain into a human-readable company name.

    'example-education.org'      → 'Example Education'
    'my-company.com'             → 'My Company'
    """
    parts = domain.split(".")
    slug = parts[0] if len(parts) <= 2 else ".".join(parts[:-2])
    slug = slug.replace("-", " ").replace("_", " ")
    return " ".join(w.capitalize() for w in slug.split() if w)


def _enrich_client(client: dict) -> dict:
    """Add display_name derived from domain when no explicit name is stored."""
    if not client.get("name") and client.get("domain"):
        client["display_name"] = _segment_domain_name(client["domain"])
    else:
        client["display_name"] = client.get("name") or client.get("domain") or "Unknown"
    return client


def _enrich_ticket_client(ticket: dict) -> dict:
    """Add client_display_name to a ticket dict using the same logic as _enrich_client."""
    domain = ticket.get("client_domain")
    name = ticket.get("client_name")
    if name:
        ticket["client_display_name"] = name
    elif domain:
        ticket["client_display_name"] = _segment_domain_name(domain)
    else:
        ticket["client_display_name"] = None
    return ticket


async def list_clients(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 50,
    search: str | None = None,
) -> list[dict]:
    where = (
        "WHERE toLower(c.name) CONTAINS toLower($search) OR toLower(c.domain) CONTAINS toLower($search)"
        if search
        else ""
    )
    result = await session.run(
        f"""
        MATCH (c:Client)
        {where}
        OPTIONAL MATCH (t:Ticket)-[:FROM]->(c)
        OPTIONAL MATCH (c)-[:WORKS_FOR]->(parent:Client)
        WITH c, parent, count(t) AS ticket_count
        RETURN c {{
            .name, .domain, ticket_count: ticket_count,
            parent_domain: parent.domain,
            parent_name: parent.name
        }} AS client
        ORDER BY ticket_count DESC, c.name
        SKIP $offset LIMIT $limit
        """,
        offset=offset,
        limit=limit,
        search=search or "",
    )
    records = await result.data()
    return [_enrich_client(r["client"]) for r in records]


@_log_slow
async def get_client(session: AsyncSession, domain: str) -> dict | None:
    result = await session.run(
        """
        MATCH (c:Client {domain: $domain})
        OPTIONAL MATCH (t:Ticket)-[:FROM]->(c)
        OPTIONAL MATCH (u:User)-[:ASSIGNED_TO]->(t)
        OPTIONAL MATCH (c)-[:WORKS_FOR]->(parent:Client)
        WITH c, parent, count(DISTINCT t) AS ticket_count,
             collect(DISTINCT u.name) AS agents,
             collect(DISTINCT t {.id, .subject, .status, .created_at, .source_system})[..50] AS tickets
        RETURN c {
            .name, .domain, ticket_count: ticket_count, agents: agents, tickets: tickets,
            parent_domain: parent.domain,
            parent_name: parent.name
        } AS client
        """,
        domain=domain,
    )
    record = await result.single()
    return _enrich_client(record["client"]) if record else None


async def link_client_parent(session: AsyncSession, child_domain: str, parent_domain: str) -> bool:
    """Create a WORKS_FOR relationship from child to parent client."""
    result = await session.run(
        """
        MATCH (child:Client {domain: $child_domain})
        MATCH (parent:Client {domain: $parent_domain})
        MERGE (child)-[:WORKS_FOR]->(parent)
        RETURN count(*) AS n
        """,
        child_domain=child_domain,
        parent_domain=parent_domain,
    )
    record = await result.single()
    return bool(record and record["n"] > 0)


async def unlink_client_parent(session: AsyncSession, child_domain: str) -> bool:
    """Remove the WORKS_FOR relationship from a client."""
    result = await session.run(
        """
        MATCH (child:Client {domain: $child_domain})-[r:WORKS_FOR]->(:Client)
        DELETE r
        RETURN count(r) AS n
        """,
        child_domain=child_domain,
    )
    record = await result.single()
    return bool(record and record["n"] > 0)
