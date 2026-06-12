from neo4j import AsyncSession

from ._shared import _log_slow


@_log_slow
async def vector_search(
    session: AsyncSession,
    query_embedding: list[float],
    threshold: float = 0.7,
    limit: int = 10,
) -> list[dict]:
    result = await session.run(
        """
        CALL db.index.vector.queryNodes('chunk_embedding', $limit, $embedding)
        YIELD node AS c, score
        WHERE score >= $threshold
        RETURN c.id AS id, c.content AS content, c.document_id AS document_id,
               c.page_number AS page_number, score
        ORDER BY score DESC
        """,
        embedding=query_embedding,
        threshold=threshold,
        limit=limit,
    )
    return await result.data()


def _rrf_merge(
    dense: list[dict],
    lexical: list[dict],
    limit: int,
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion — merges dense and lexical result lists.

    Each result gets score = sum of 1/(rank + k) across the lists it appears in.
    k=60 is the standard RRF constant (Robertson et al. 2009).
    """
    scores: dict[str, dict] = {}
    for rank, r in enumerate(dense):
        rid = str(r["id"])
        scores[rid] = {**r, "score": scores.get(rid, {}).get("score", 0.0) + 1.0 / (rank + 1 + k)}
    for rank, r in enumerate(lexical):
        rid = str(r["id"])
        if rid not in scores:
            scores[rid] = {**r, "score": 0.0}
        scores[rid]["score"] += 1.0 / (rank + 1 + k)
    merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return merged[:limit]


@_log_slow
async def hybrid_search(
    session: AsyncSession,
    query_text: str,
    query_embedding: list[float],
    threshold: float = 0.7,
    limit: int = 10,
) -> list[dict]:
    """Hybrid search: dense vector (cosine) + lexical full-text, merged via RRF.

    Fetches 2x limit from each index to give RRF enough candidates to re-rank,
    then returns the top `limit` results.
    """
    fetch_n = limit * 2

    # Dense leg
    dense_result = await session.run(
        """
        CALL db.index.vector.queryNodes('chunk_embedding', $limit, $embedding)
        YIELD node AS c, score
        WHERE score >= $threshold
        RETURN c.id AS id, c.content AS content, c.document_id AS document_id,
               c.page_number AS page_number, score
        ORDER BY score DESC
        """,
        embedding=query_embedding,
        threshold=threshold,
        limit=fetch_n,
    )
    dense = await dense_result.data()

    # Lexical leg (full-text / BM25 via Lucene)
    lexical_result = await session.run(
        """
        CALL db.index.fulltext.queryNodes('chunk_fulltext', $search_query)
        YIELD node AS c, score
        RETURN c.id AS id, c.content AS content, c.document_id AS document_id,
               c.page_number AS page_number, score
        ORDER BY score DESC
        LIMIT $limit
        """,
        search_query=query_text,
        limit=fetch_n,
    )
    lexical = await lexical_result.data()

    return _rrf_merge(dense, lexical, limit=limit)


@_log_slow
async def ticket_vector_search(
    session: AsyncSession,
    query_embedding: list[float],
    threshold: float = 0.7,
    limit: int = 5,
) -> list[dict]:
    result = await session.run(
        """
        CALL db.index.vector.queryNodes('ticket_embedding_gemini', $limit, $embedding)
        YIELD node AS t, score
        WHERE score >= $threshold
        OPTIONAL MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
        RETURN t.id AS id, t.subject AS subject, t.preview AS preview,
               t.status AS status, score,
               collect(assigned.email) AS assigned_to
        ORDER BY score DESC
        """,
        embedding=query_embedding,
        threshold=threshold,
        limit=limit,
    )
    return await result.data()
