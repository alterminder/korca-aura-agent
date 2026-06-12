from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    tags: list[str] = []


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float
    page_number: int | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_chunks: int = Field(default=8, ge=1, le=20)


class AskSource(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    score: float


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[AskSource]
