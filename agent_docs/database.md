# Database — Neo4j Aura

Korca Aura uses a Neo4j Aura cloud database. Do not add local Neo4j fallbacks or self-hosted `korca` Neo4j references.

Query layer: `backend/app/db/` — `connection.py` + `queries.py`

## Vector Search Pattern

```python
result = await session.run("""
    CALL db.index.vector.queryNodes('chunk_embedding', $limit, $embedding)
    YIELD node AS c, score
    WHERE score >= $threshold
    RETURN c.id AS id, c.content AS content, c.document_id AS document_id, score
    ORDER BY score DESC
""", embedding=embedding, threshold=0.7, limit=10)
```

## Production Access

Application pods run in Kubernetes, but database access is through Neo4j Aura credentials injected from production secrets:

- `NEO4J_URI_AURA`
- `NEO4J_USER_AURA`
- `NEO4J_PASS_AURA`
- `NEO4J_DATABASE_AURA`

## Useful Queries

```cypher
-- Node counts by label
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC

-- Ingest status breakdown
MATCH (t:Ticket) RETURN t.ingest_status AS status, count(t) AS count ORDER BY count DESC

-- Routing accuracy
MATCH (routed:User)-[:ROUTED_TO]->(t:Ticket)
MATCH (assigned:User)-[:ASSIGNED_TO]->(t)
WITH routed, t, assigned.email AS correct
WHERE correct IS NOT NULL
RETURN
  count(t) AS verifiable,
  sum(CASE WHEN routed.email = correct THEN 1 ELSE 0 END) AS correct,
  round(100.0 * sum(CASE WHEN routed.email = correct THEN 1 ELSE 0 END) / count(t), 1) AS accuracy_pct
```
