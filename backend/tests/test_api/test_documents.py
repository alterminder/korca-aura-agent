from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes import documents
from app.config import settings as _settings
from app.db.connection import get_db
from app.main import app


@pytest.fixture(autouse=True)
def override_db():
    """Prevent all document upload tests from hitting a real Neo4j driver."""
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = mock_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_upload_rejects_wrong_content_type(client):
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake content", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf_bytes_with_pdf_content_type(client):
    # PNG magic bytes smuggled in with a PDF content-type header
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("evil.pdf", png_bytes, "application/pdf")},
    )
    assert resp.status_code == 400
    assert "not a valid PDF" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client):
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "not a valid PDF" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(_settings, "upload_max_size_mb", 1)
    big_pdf = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("big.pdf", big_pdf, "application/pdf")},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_upload_accepts_valid_pdf(client):
    fake_pdf = b"%PDF-1.4\n%%EOF"
    with (
        patch(
            "app.services.storage.save_upload_stream",
            new_callable=AsyncMock,
            return_value="fake_hash",
        ),
        patch("app.services.storage.finalize_temp_pdf", return_value="/tmp/fake.pdf"),
        patch("app.worker.process_document") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("real.pdf", fake_pdf, "application/pdf")},
        )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_upload_deduplicates_existing_document(client):
    """Duplicate upload returns the existing document id without creating a new node."""
    fake_pdf = b"%PDF-1.4\n%%EOF"
    existing_id = "already-exists-doc-id"

    dup_result = AsyncMock()
    dup_result.single = AsyncMock(return_value={"id": existing_id})
    from app.db.connection import get_db as _get_db

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=dup_result)

    async def mock_get_db_dup():
        yield mock_session

    app.dependency_overrides[_get_db] = mock_get_db_dup
    try:
        with (
            patch(
                "app.services.storage.save_upload_stream",
                new_callable=AsyncMock,
                return_value="dup_hash",
            ),
            patch(
                "app.services.storage.get_temp_pdf_path", return_value=MagicMock(unlink=MagicMock())
            ),
            patch("app.api.routes.documents.set_status", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/api/documents/upload",
                files={"file": ("dup.pdf", fake_pdf, "application/pdf")},
            )
    finally:
        app.dependency_overrides.pop(_get_db, None)

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == existing_id
    assert body["message"] == "Document already exists"
    # No CREATE query should have been issued — only the dedup MATCH
    assert mock_session.run.call_count == 1


def _return_annotation_name(function) -> str:
    annotation = get_type_hints(function)["return"]
    origin = get_origin(annotation)
    if origin is list:
        (item_type,) = get_args(annotation)
        return f"list[{item_type.__name__}]"
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return str(annotation).replace("app.api.routes.documents.", "")


def test_document_route_handlers_have_typed_response_models():
    assert _return_annotation_name(documents.list_documents) == "list[DocumentResponse]"
    assert _return_annotation_name(documents.get_document) == "DocumentResponse"


@pytest.mark.asyncio
async def test_list_documents_returns_response_models(monkeypatch):
    monkeypatch.setattr(
        documents.queries,
        "list_documents",
        AsyncMock(
            return_value=[
                {
                    "id": "doc_1",
                    "title": "DNS runbook",
                    "filename": "dns.pdf",
                    "content_hash": "abc123",
                    "page_count": 3,
                    "chunk_count": 5,
                    "tags": ["dns"],
                    "experts": [{"name": "Alice", "email": "a@x.com"}],
                    "created_at": "2026-06-01T10:00:00Z",
                    "status": "completed",
                }
            ]
        ),
    )

    result = await documents.list_documents(db=object(), offset=0, limit=20)

    assert [type(item).__name__ for item in result] == ["DocumentResponse"]
    assert result[0].experts[0].name == "Alice"
    assert result[0].chunks is None


@pytest.mark.asyncio
async def test_list_documents_tolerates_sparse_rows(monkeypatch):
    monkeypatch.setattr(
        documents.queries, "list_documents", AsyncMock(return_value=[{"id": "doc_min"}])
    )

    result = await documents.list_documents(db=object(), offset=0, limit=20)

    assert result[0].id == "doc_min"
    assert result[0].title is None
    assert result[0].tags == []
    assert result[0].experts == []


@pytest.mark.asyncio
async def test_get_document_returns_detail_with_chunks(monkeypatch):
    # The detail query's chunk projection omits document_id, so the embedded
    # chunk model must tolerate it.
    monkeypatch.setattr(
        documents.queries,
        "get_document_with_chunks",
        AsyncMock(
            return_value={
                "id": "doc_1",
                "title": "DNS runbook",
                "status": "completed",
                "tags": [],
                "chunks": [
                    {
                        "id": "chunk_1",
                        "chunk_index": 0,
                        "page_number": 1,
                        "content": "hello",
                        "token_count": 4,
                    }
                ],
            }
        ),
    )

    result = await documents.get_document("doc_1", db=object())

    assert type(result).__name__ == "DocumentResponse"
    assert result.chunks is not None
    assert type(result.chunks[0]).__name__ == "DocumentChunkItem"
    assert result.chunks[0].content == "hello"


@pytest.mark.asyncio
async def test_get_document_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(
        documents.queries, "get_document_with_chunks", AsyncMock(return_value=None)
    )

    with pytest.raises(HTTPException) as exc:
        await documents.get_document("nope", db=object())

    assert exc.value.status_code == 404
