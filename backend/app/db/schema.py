import structlog
from neo4j import AsyncSession

logger = structlog.get_logger()


async def init_schema(session: AsyncSession) -> None:
    logger.info("Initializing Neo4j schema")

    # Constraints (uniqueness + existence)
    constraints = [
        "CREATE CONSTRAINT user_email IF NOT EXISTS FOR (u:User) REQUIRE u.email IS UNIQUE",
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT document_hash IF NOT EXISTS FOR (d:Document) REQUIRE d.content_hash IS UNIQUE",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT ticket_id IF NOT EXISTS FOR (t:Ticket) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT client_domain IF NOT EXISTS FOR (c:Client) REQUIRE c.domain IS UNIQUE",
    ]

    # Indexes for common lookups
    indexes = [
        "CREATE INDEX document_status IF NOT EXISTS FOR (d:Document) ON (d.status)",
        "CREATE INDEX document_created IF NOT EXISTS FOR (d:Document) ON (d.created_at)",
        "CREATE INDEX chunk_document IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
        "CREATE INDEX ticket_status IF NOT EXISTS FOR (t:Ticket) ON (t.status)",
        "CREATE INDEX ticket_created IF NOT EXISTS FOR (t:Ticket) ON (t.created_at)",
    ]

    # Full-text indexes for hybrid search (lexical / sparse leg of RRF)
    fulltext_indexes = [
        """
        CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS
        FOR (c:Chunk) ON EACH [c.content]
        """,
        """
        CREATE FULLTEXT INDEX ticket_fulltext IF NOT EXISTS
        FOR (t:Ticket) ON EACH [t.subject, t.content]
        """,
    ]

    # Vector indexes for semantic search. Document chunks and Aura tickets both
    # use 3072-d Gemini embeddings, stored in separate vector indexes.
    vector_indexes = [
        """
        CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}
        """,
        """
        CREATE VECTOR INDEX ticket_embedding_gemini IF NOT EXISTS
        FOR (t:Ticket) ON (t.gemini_embedding)
        OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}
        """,
    ]

    for stmt in constraints + indexes + fulltext_indexes + vector_indexes:
        await session.run(stmt)

    # Create then remove RoutingEvent tokens so read queries do not emit Neo4j
    # "label/relationship/property does not exist" warnings before the first
    # real Aura routing event is created.
    await session.run(
        """
        CREATE (t:__KorcaSchemaSeed {
            id: "routing_event_ticket",
            aura_routing_error: "seed",
            teamwork_action_error: "seed"
        })
        CREATE (e:RoutingEvent {
            id: "routing_event_seed",
            suggested_email: "seed@example.invalid",
            suggested_name: "Seed Expert",
            outcome: "seed",
            created_at: "seed"
        })
        CREATE (t)-[:HAS_ROUTING_EVENT]->(e)
        CREATE (e)-[:RECOMMENDED_EXPERT]->(:__KorcaSchemaSeed {id: "routing_event_user"})
        WITH e
        MATCH (n:__KorcaSchemaSeed)
        DETACH DELETE n
        WITH e
        DETACH DELETE e
        """
    )

    # Backfill source_system for tickets imported before this field was added
    await session.run(
        "MATCH (t:Ticket) WHERE t.source_system IS NULL OR t.source_system = '' SET t.source_system = 'teamwork'"
    )

    logger.info("Neo4j schema initialized")
