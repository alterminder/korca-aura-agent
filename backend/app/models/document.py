from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: str
    status: Literal["processing", "completed", "failed"]
    message: str


class Document(BaseModel):
    id: str
    title: str
    filename: str
    author_email: str | None = None
    content_hash: str
    page_count: int
    chunk_count: int = 0
    tags: list[str] = []
    created_at: datetime
    processed_at: datetime | None = None
    status: Literal["pending", "processing", "completed", "failed"]
    error_message: str | None = None


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    page_number: int
    chunk_index: int
    content: str
    embedding: list[float] | None = None
    token_count: int = 0


class DocumentStatusEvent(BaseModel):
    id: str
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int = 0
    message: str | None = None


class DocumentExpert(BaseModel):
    name: str
    email: str


class AddExpertRequest(BaseModel):
    email: str
