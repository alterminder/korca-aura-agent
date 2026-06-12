from neo4j import AsyncSession

from ._shared import _log_slow, user_uid


async def list_users(session: AsyncSession) -> list[dict]:
    result = await session.run(
        """
        MATCH (u:User)
        OPTIONAL MATCH (u)-[:ASSIGNED_TO]->(t:Ticket)
        OPTIONAL MATCH (t)-[:TAGGED]->(tp:Topic)
        OPTIONAL MATCH (u)-[:HAS_SKILL]->(s:Skill)
        OPTIONAL MATCH (u)-[:REPORTS_TO]->(manager:User)
        WITH u, count(DISTINCT t) AS tickets_resolved,
             collect(DISTINCT tp.name) AS topics,
             collect(DISTINCT s.name) AS skills,
             manager
        RETURN u {.*, tickets_resolved: tickets_resolved, topics: topics, skills: skills,
                  manager_name: manager.name, manager_email: manager.email} AS user
        ORDER BY tickets_resolved DESC, u.name
        """
    )
    records = await result.data()
    return [r["user"] for r in records]


async def get_user(session: AsyncSession, user_id: str) -> dict | None:
    result = await session.run(
        """
        MATCH (u:User {id: $id})
        OPTIONAL MATCH (u)-[:HAS_SKILL]->(s:Skill)
        OPTIONAL MATCH (u)-[:REPORTS_TO]->(manager:User)
        WITH u, collect(DISTINCT s.name) AS skills, manager
        RETURN u {.*, skills: skills, manager_name: manager.name, manager_email: manager.email} AS user
        """,
        id=user_id,
    )
    record = await result.single()
    return record["user"] if record else None


async def update_user_profile(
    session: AsyncSession,
    user_id: str,
    department: str | None,
    title: str | None,
    manager_email: str | None,
    skills: list[str] | None,
    skill_embeddings: dict[str, list[float]] | None = None,
) -> list[str] | None:
    """Update org chart fields on a User node. Returns None if user not found, else existing skills list."""
    check = await session.run(
        "MATCH (u:User {id: $id}) RETURN u.skills AS skills LIMIT 1",
        id=user_id,
    )
    row = await check.single()
    if not row:
        return None
    existing_skills: list[str] = list(row["skills"] or [])

    await session.run(
        """
        MATCH (u:User {id: $id})
        SET u.department = CASE WHEN $department IS NOT NULL THEN (CASE WHEN $department = '' THEN null ELSE $department END) ELSE u.department END,
            u.title = CASE WHEN $title IS NOT NULL THEN (CASE WHEN $title = '' THEN null ELSE $title END) ELSE u.title END
        """,
        id=user_id,
        department=department,
        title=title,
    )

    # Set manager relationship — empty string means "remove manager"
    if manager_email is not None:
        await session.run(
            "MATCH (u:User {id: $id}) OPTIONAL MATCH (u)-[r:REPORTS_TO]->() DELETE r",
            id=user_id,
        )
        if manager_email:
            await session.run(
                """
                MATCH (u:User {id: $id}), (m:User {email: $manager_email})
                MERGE (u)-[:REPORTS_TO]->(m)
                """,
                id=user_id,
                manager_email=manager_email,
            )

    # Replace skills — batch all skill upserts in one UNWIND round-trip
    if skills is not None:
        r = await session.run(
            "MATCH (u:User {id: $id}) OPTIONAL MATCH (u)-[rel:HAS_SKILL]->() DELETE rel",
            id=user_id,
        )
        await r.consume()
        skill_rows = [
            {"name": s.strip(), "embedding": (skill_embeddings or {}).get(s.strip().lower())}
            for s in skills
            if s.strip()
        ]
        if skill_rows:
            r = await session.run(
                """
                UNWIND $skills AS row
                MERGE (s:Skill {name: toLower(row.name)})
                SET s.display_name = row.name,
                    s.embedding = CASE WHEN row.embedding IS NOT NULL THEN row.embedding ELSE s.embedding END
                WITH s
                MATCH (u:User {id: $id})
                MERGE (u)-[:HAS_SKILL]->(s)
                """,
                skills=skill_rows,
                id=user_id,
            )
            await r.consume()

    return existing_skills


async def create_user(
    session: AsyncSession,
    name: str,
    email: str,
    title: str | None,
    department: str | None,
    skills: list[str],
    skill_embeddings: dict[str, list[float]] | None = None,
) -> dict:
    """Create a new User node with optional org-chart fields and skills.

    Uses email as the uniqueness key (MERGE). Returns the created/updated user.
    """
    user_id = user_uid(email)
    await session.run(
        """
        MERGE (u:User {email: $email})
        SET u.id     = coalesce(u.id, $id),
            u.name   = $name,
            u.title  = CASE WHEN $title IS NOT NULL THEN $title ELSE u.title END,
            u.department = CASE WHEN $department IS NOT NULL THEN $department ELSE u.department END
        """,
        id=user_id,
        email=email,
        name=name,
        title=title,
        department=department,
    )
    # Replace skills — batch all skill upserts in one UNWIND round-trip
    r = await session.run(
        "MATCH (u:User {email: $email}) OPTIONAL MATCH (u)-[rel:HAS_SKILL]->() DELETE rel",
        email=email,
    )
    await r.consume()
    skill_rows = [
        {"name": s.strip(), "embedding": (skill_embeddings or {}).get(s.strip().lower())}
        for s in skills
        if s.strip()
    ]
    if skill_rows:
        r = await session.run(
            """
            UNWIND $skills AS row
            MERGE (s:Skill {name: toLower(row.name)})
            SET s.display_name = row.name,
                s.embedding = CASE WHEN row.embedding IS NOT NULL THEN row.embedding ELSE s.embedding END
            WITH s
            MATCH (u:User {email: $email})
            MERGE (u)-[:HAS_SKILL]->(s)
            """,
            skills=skill_rows,
            email=email,
        )
        await r.consume()
    # Fetch the id back (MERGE may have preserved an existing id)
    result = await session.run(
        "MATCH (u:User {email: $email}) RETURN u.id AS id",
        email=email,
    )
    record = await result.single()
    assert record is not None, f"create_user: could not re-fetch user {email}"
    user = await get_user(session, record["id"])
    assert user is not None, f"create_user: get_user returned None for {email}"
    return user


async def delete_user(session: AsyncSession, user_id: str) -> bool:
    """Remove a User node and all its relationships from the graph.

    GUARDRAIL: Graph-local only. Does not touch Teamwork.
    Tickets assigned to the user remain in the graph; only the user's node and
    relationships are removed.
    """
    exists = await session.run(
        "MATCH (u:User {id: $id}) RETURN count(u) AS n",
        id=user_id,
    )
    record = await exists.single()
    if not record or record["n"] == 0:
        return False
    await session.run(
        "MATCH (u:User {id: $id}) DETACH DELETE u",
        id=user_id,
    )
    return True


async def get_expert_ticket_summaries(
    session: AsyncSession, user_id: str, limit: int = 40
) -> list[str]:
    """Return Teamwork ticket summaries assigned to this expert for skill generation."""
    result = await session.run(
        """
        MATCH (u:User {id: $id})-[:ASSIGNED_TO]->(t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND toLower(coalesce(t.status, '')) IN ['closed', 'solved', 'resolved']
          AND t.content IS NOT NULL AND t.content <> ''
        RETURN coalesce(t.content, '') AS content
        ORDER BY t.created_at DESC
        LIMIT $limit
        """,
        id=user_id,
        limit=limit,
    )
    records = await result.data()
    return [r["content"] for r in records if r["content"]]


async def list_teamwork_experts_for_skill_generation(session: AsyncSession) -> list[dict]:
    """Return Teamwork assignees with closed ticket history and no saved skills."""
    result = await session.run(
        """
        MATCH (u:User)-[:ASSIGNED_TO]->(t:Ticket)
        WHERE t.source_system = 'teamwork'
          AND toLower(coalesce(t.status, '')) IN ['closed', 'solved', 'resolved']
        OPTIONAL MATCH (u)-[:HAS_SKILL]->(s:Skill)
        WITH u, count(DISTINCT t) AS ticket_count, count(s) AS skill_count
        WHERE ticket_count > 0 AND skill_count = 0
        RETURN u.id AS id, u.name AS name, u.email AS email, ticket_count
        ORDER BY ticket_count DESC, u.name
        """
    )
    return [dict(r) for r in await result.data()]


async def get_user_authored_docs(session: AsyncSession, user_id: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (:User {id: $id})-[:AUTHORED]->(d:Document)
        RETURN d {.*} AS doc
        ORDER BY d.created_at DESC
        """,
        id=user_id,
    )
    records = await result.data()
    return [r["doc"] for r in records]


@_log_slow
async def compare_experts(
    session: AsyncSession,
    id_a: str,
    id_b: str,
) -> dict | None:
    """Return shared/exclusive clients and skills for two experts."""
    # Fetch both users
    users_result = await session.run(
        """
        MATCH (u:User) WHERE u.id IN [$id_a, $id_b]
        OPTIONAL MATCH (u)-[:HAS_SKILL]->(s:Skill)
        WITH u, collect(DISTINCT s.name) AS skills
        RETURN u.id AS id, u.name AS name, u.email AS email, skills
        """,
        id_a=id_a,
        id_b=id_b,
    )
    users = {r["id"]: r for r in await users_result.data()}
    if id_a not in users or id_b not in users:
        return None

    # Fetch client ticket counts for both experts in one query
    clients_result = await session.run(
        """
        MATCH (u:User) WHERE u.id IN [$id_a, $id_b]
        MATCH (u)-[:ASSIGNED_TO]->(t:Ticket)-[:FROM]->(c:Client)
        RETURN u.id AS user_id, c.name AS client, count(t) AS ticket_count
        ORDER BY ticket_count DESC
        """,
        id_a=id_a,
        id_b=id_b,
    )
    rows = await clients_result.data()

    # Aggregate into {client: {id_a: n, id_b: n}}
    client_map: dict[str, dict[str, int]] = {}
    for row in rows:
        name = row["client"]
        if name not in client_map:
            client_map[name] = {id_a: 0, id_b: 0}
        client_map[name][row["user_id"]] = row["ticket_count"]

    shared_clients = []
    only_a = []
    only_b = []
    for name, counts in sorted(client_map.items(), key=lambda x: -(x[1][id_a] + x[1][id_b])):
        ca, cb = counts[id_a], counts[id_b]
        if ca > 0 and cb > 0:
            shared_clients.append({"name": name, "count_a": ca, "count_b": cb})
        elif ca > 0:
            only_a.append({"name": name, "count": ca})
        else:
            only_b.append({"name": name, "count": cb})

    # Skills comparison
    skills_a = set(users[id_a]["skills"] or [])
    skills_b = set(users[id_b]["skills"] or [])
    shared_skills = sorted(skills_a & skills_b)
    only_a_skills = sorted(skills_a - skills_b)
    only_b_skills = sorted(skills_b - skills_a)

    return {
        "expert_a": {"id": id_a, "name": users[id_a]["name"], "email": users[id_a]["email"]},
        "expert_b": {"id": id_b, "name": users[id_b]["name"], "email": users[id_b]["email"]},
        "shared_clients": shared_clients,
        "only_a_clients": only_a,
        "only_b_clients": only_b,
        "shared_skills": shared_skills,
        "only_a_skills": only_a_skills,
        "only_b_skills": only_b_skills,
    }
