import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from app.api.deps import DBDep
from app.config import settings
from app.db import queries
from app.exceptions import DomainError
from app.limiter import limiter
from app.models.document import (
    AddExpertRequest,
    DocumentExpert,
    DocumentStatusEvent,
    DocumentUploadResponse,
)
from app.services import storage as storage_svc
from app.services.job_status import delete_status, get_status, set_status

logger = structlog.get_logger()
router = APIRouter()

_DOC_NOT_FOUND = "Document not found"
_PDF_NOT_FOUND = "PDF not found"


@router.post(
    "/upload",
    status_code=202,
    responses={
        400: {"description": "File is not a PDF or fails magic-byte check"},
        500: {"description": "Failed to save or store uploaded file"},
    },
)
@limiter.limit("5/minute")
async def upload_document(
    request: Request,
    db: DBDep,
    file: UploadFile = File(...),
    author_email: str | None = None,
    tags: str = "",
) -> DocumentUploadResponse:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Read the first 4 bytes of the upload stream to verify magic PDF signature
    header = await file.read(4)
    if header != b"%PDF":
        raise HTTPException(status_code=400, detail="File is not a valid PDF")

    # Generate a temporary path for the streaming upload
    temp_id = uuid.uuid4().hex
    temp_path = storage_svc.get_temp_pdf_path(temp_id)

    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    try:
        content_hash = await storage_svc.save_upload_stream(
            file=file,
            dest_path=temp_path,
            header=header,
            max_bytes=max_bytes,
        )
    except (HTTPException, DomainError):
        # Re-raise HTTPExceptions and DomainErrors directly
        raise
    except Exception as e:
        # Clean up any partial files on unexpected failure
        if temp_path.exists():
            temp_path.unlink()
        logger.error("Failed to stream upload", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    # Deduplication check
    result = await db.run(
        "MATCH (d:Document {content_hash: $hash}) RETURN d.id AS id LIMIT 1",
        hash=content_hash,
    )
    existing = await result.single()
    if existing:
        temp_path.unlink(missing_ok=True)
        existing_id = existing["id"]
        await set_status(existing_id, "completed", 100, "Document already exists")
        return DocumentUploadResponse(
            id=existing_id, status="completed", message="Document already exists"
        )

    doc_id = uuid.uuid4().hex
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    now = datetime.now(UTC).isoformat()

    # Create pending Document node
    await db.run(
        """
        CREATE (d:Document {
            id: $id,
            title: $title,
            filename: $filename,
            author_email: $author,
            content_hash: $hash,
            page_count: 0,
            chunk_count: 0,
            status: 'pending',
            created_at: $now
        })
        """,
        id=doc_id,
        title=file.filename or "Untitled",
        filename=file.filename or "upload.pdf",
        author=author_email,
        hash=content_hash,
        now=now,
    )

    # Move temporary file to final persistent PVC storage.
    # If the move fails, clean up the temp file and the graph node so there is
    # no dangling Document with a missing PDF on disk.
    try:
        pdf_path = storage_svc.finalize_temp_pdf(temp_path, doc_id)
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        await db.run("MATCH (d:Document {id: $id}) DELETE d", id=doc_id)
        logger.error("Failed to finalize PDF, document rolled back", doc_id=doc_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to store uploaded file")

    from app.worker import process_document as _process_doc_task

    _process_doc_task.delay(doc_id, str(pdf_path), author_email, tag_list)

    return DocumentUploadResponse(
        id=doc_id, status="processing", message="Upload accepted, processing started"
    )


class DocumentChunkItem(BaseModel):
    # Embedded chunk summary from the detail query (no document_id) — tolerate
    # partial shapes and keep any extras.
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    chunk_index: int | None = None
    page_number: int | None = None
    content: str | None = None
    token_count: int | None = None


class DocumentResponse(BaseModel):
    """Compatible with the frontend `Document` type, but more tolerant. The list
    query adds `experts`; the detail query adds `chunks`; only `id` is
    guaranteed, so the rest stay optional/nullable to avoid rejecting rows."""

    id: str
    title: str | None = None
    filename: str | None = None
    author_email: str | None = None
    content_hash: str | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    tags: list[str] = Field(default_factory=list)
    experts: list[DocumentExpert] = Field(default_factory=list)
    created_at: str | None = None
    processed_at: str | None = None
    status: str | None = None
    error_message: str | None = None
    chunks: list[DocumentChunkItem] | None = None


def _document_response(data: dict[str, Any]) -> DocumentResponse:
    return DocumentResponse.model_validate(data)


def _document_responses(rows: list[dict[str, Any]]) -> list[DocumentResponse]:
    return [_document_response(row) for row in rows]


@router.get("")
async def list_documents(
    db: DBDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> list[DocumentResponse]:
    rows = await queries.list_documents(db, offset=offset, limit=limit)
    return _document_responses(rows)


@router.get("/{document_id}", responses={404: {"description": _DOC_NOT_FOUND}})
async def get_document(document_id: str, db: DBDep) -> DocumentResponse:
    doc = await queries.get_document_with_chunks(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=_DOC_NOT_FOUND)
    return _document_response(doc)


async def _poll_document_status(document_id: str, db: DBDep) -> tuple[str, bool]:
    """Single SSE polling tick. Returns (json_data, should_break)."""
    event = await get_status(document_id)
    if event:
        return event.model_dump_json(), event.status in ("completed", "failed")

    doc = await queries.get_document(db, document_id)
    if doc:
        db_status = doc.get("status", "pending")
        progress = 100 if db_status == "completed" else 0
        event = DocumentStatusEvent(id=document_id, status=db_status, progress=progress)
        await set_status(document_id, db_status, progress)
        return event.model_dump_json(), db_status in ("completed", "failed")

    return DocumentStatusEvent(
        id=document_id, status="pending", progress=0
    ).model_dump_json(), False


@router.get("/{document_id}/status")
async def document_status(document_id: str, db: DBDep) -> EventSourceResponse:
    async def generator():
        for _ in range(300):  # max ~5 min
            data, done = await _poll_document_status(document_id, db)
            yield {"data": data}
            if done:
                break
            await asyncio.sleep(1)

    return EventSourceResponse(generator())


@router.delete("/{document_id}", status_code=204, responses={404: {"description": _DOC_NOT_FOUND}})
async def delete_document(document_id: str, db: DBDep) -> None:
    if not await queries.get_document(db, document_id):
        raise HTTPException(status_code=404, detail=_DOC_NOT_FOUND)
    await queries.delete_document(db, document_id)
    storage_svc.delete_pdf(document_id)
    await delete_status(document_id)


@router.get("/{document_id}/experts", responses={404: {"description": _DOC_NOT_FOUND}})
async def get_document_experts(document_id: str, db: DBDep) -> list[DocumentExpert]:
    if not await queries.get_document(db, document_id):
        raise HTTPException(status_code=404, detail=_DOC_NOT_FOUND)
    rows = await queries.get_document_experts(db, document_id)
    return [DocumentExpert(**r) for r in rows]


@router.post(
    "/{document_id}/experts",
    status_code=201,
    responses={
        404: {"description": "Document or user not found"},
    },
)
async def add_document_expert(
    document_id: str, body: AddExpertRequest, db: DBDep
) -> DocumentExpert:
    if not await queries.get_document(db, document_id):
        raise HTTPException(status_code=404, detail=_DOC_NOT_FOUND)
    row = await queries.add_document_expert(db, document_id, body.email)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return DocumentExpert(**row)


@router.delete(
    "/{document_id}/experts",
    status_code=204,
    responses={404: {"description": _DOC_NOT_FOUND}},
)
async def remove_document_expert(
    document_id: str,
    email: Annotated[str, Query()],
    db: DBDep,
) -> None:
    if not await queries.get_document(db, document_id):
        raise HTTPException(status_code=404, detail=_DOC_NOT_FOUND)
    await queries.remove_document_expert(db, document_id, email)


@router.get("/{document_id}/download", responses={404: {"description": _PDF_NOT_FOUND}})
async def download_document(document_id: str) -> FileResponse:
    try:
        path = storage_svc.get_pdf_path(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_PDF_NOT_FOUND) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found on disk")
    return FileResponse(path, media_type="application/pdf", filename=f"{document_id}.pdf")
