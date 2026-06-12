from neo4j import AsyncSession


async def list_documents(session: AsyncSession, offset: int = 0, limit: int = 20) -> list[dict]:
    result = await session.run(
        """
        MATCH (d:Document)
        OPTIONAL MATCH (d)-[:TAGGED]->(t:Topic)
        WITH d, collect(t.name) AS tags
        OPTIONAL MATCH (u:User)-[:EXPERT_IN]->(d)
        WITH d, tags, collect(CASE WHEN u IS NOT NULL THEN {name: u.name, email: u.email} END) AS experts
        RETURN d {.*, tags: tags, experts: [e IN experts WHERE e IS NOT NULL]} AS doc
        ORDER BY d.created_at DESC
        SKIP $offset LIMIT $limit
        """,
        offset=offset,
        limit=limit,
    )
    records = await result.data()
    return [r["doc"] for r in records]


async def get_document(session: AsyncSession, document_id: str) -> dict | None:
    result = await session.run(
        """
        MATCH (d:Document {id: $id})
        OPTIONAL MATCH (d)-[:TAGGED]->(t:Topic)
        WITH d, collect(t.name) AS tags
        RETURN d {.*, tags: tags} AS doc
        """,
        id=document_id,
    )
    record = await result.single()
    return record["doc"] if record else None


async def get_document_with_chunks(session: AsyncSession, document_id: str) -> dict | None:
    result = await session.run(
        """
        MATCH (d:Document {id: $id})
        OPTIONAL MATCH (d)-[:TAGGED]->(t:Topic)
        WITH d, collect(DISTINCT t.name) AS tags
        OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
        WITH d, tags, c
        ORDER BY c.chunk_index
        WITH d,
             [tag IN tags WHERE tag IS NOT NULL] AS tags,
             collect(c {.id, .chunk_index, .page_number, .content, .token_count}) AS chunks
        RETURN d {.*, tags: tags} AS doc,
               [chunk IN chunks WHERE chunk.id IS NOT NULL] AS chunks
        """,
        id=document_id,
    )
    record = await result.single()
    if not record:
        return None
    doc = record["doc"]
    doc["chunks"] = record["chunks"]
    return doc


async def delete_document(session: AsyncSession, document_id: str) -> None:
    await session.run(
        """
        MATCH (d:Document {id: $id})
        OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
        DETACH DELETE d, c
        """,
        id=document_id,
    )


async def get_document_experts(session: AsyncSession, doc_id: str) -> list[dict]:
    result = await session.run(
        """
        MATCH (d:Document {id: $doc_id})
        MATCH (u:User)-[:EXPERT_IN]->(d)
        RETURN u.name AS name, u.email AS email
        ORDER BY u.name
        """,
        doc_id=doc_id,
    )
    records = await result.data()
    return [{"name": r["name"], "email": r["email"]} for r in records]


async def add_document_expert(session: AsyncSession, doc_id: str, email: str) -> dict | None:
    result = await session.run(
        """
        MATCH (d:Document {id: $doc_id})
        MATCH (u:User {email: $email})
        MERGE (u)-[:EXPERT_IN]->(d)
        RETURN u.name AS name, u.email AS email
        """,
        doc_id=doc_id,
        email=email,
    )
    record = await result.single()
    return {"name": record["name"], "email": record["email"]} if record else None


async def remove_document_expert(session: AsyncSession, doc_id: str, email: str) -> None:
    await session.run(
        """
        MATCH (u:User {email: $email})-[r:EXPERT_IN]->(d:Document {id: $doc_id})
        DELETE r
        """,
        doc_id=doc_id,
        email=email,
    )
