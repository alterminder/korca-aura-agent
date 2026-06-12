import asyncio

import pytest

from app.db.queries import documents


async def _async_value(value):
    await asyncio.sleep(0)
    return value


class _FakeResult:
    def __init__(self, record):
        self._record = record

    async def single(self):
        return await _async_value(self._record)


class _FakeSession:
    def __init__(self, record):
        self.calls = []
        self._record = record

    async def run(self, query, **params):
        self.calls.append((query, params))
        return await _async_value(_FakeResult(self._record))


@pytest.mark.asyncio
async def test_get_document_with_chunks_collapses_tags_before_matching_chunks():
    session = _FakeSession(
        {
            "doc": {"id": "doc-1", "tags": ["sop", "billing"]},
            "chunks": [{"id": "doc-1_0", "chunk_index": 0, "content": "First chunk"}],
        }
    )

    doc = await documents.get_document_with_chunks(session, "doc-1")

    assert doc["chunks"] == [{"id": "doc-1_0", "chunk_index": 0, "content": "First chunk"}]
    query, params = session.calls[0]
    tag_collect_idx = query.index("collect(DISTINCT t.name) AS tags")
    chunk_match_idx = query.index("OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)")
    assert tag_collect_idx < chunk_match_idx
    assert params == {"id": "doc-1"}
