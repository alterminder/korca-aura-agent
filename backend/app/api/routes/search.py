import structlog
from fastapi import APIRouter, Request

from app.api.deps import DBDep
from app.db.queries import hybrid_search
from app.limiter import limiter
from app.models.search import (
    AskRequest,
    AskResponse,
    AskSource,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.embeddings import embed_query
from app.services.llm import answer_question

router = APIRouter()
logger = structlog.get_logger()


@router.post("", response_model=SearchResponse)
@limiter.limit("30/minute")
async def search(request: Request, body: SearchRequest, db: DBDep) -> SearchResponse:
    query_embedding = await embed_query(body.query)
    raw = await hybrid_search(
        db,
        query_text=body.query,
        query_embedding=query_embedding,
        threshold=body.threshold,
        limit=body.limit,
    )
    results = [
        SearchResult(
            chunk_id=str(r["id"]),
            document_id=str(r["document_id"]),
            content=r["content"],
            score=r["score"],
            page_number=r.get("page_number"),
        )
        for r in raw
    ]
    return SearchResponse(query=body.query, results=results, total=len(results))


@router.post("/ask", response_model=AskResponse)
@limiter.limit("20/minute")
async def ask(request: Request, body: AskRequest, db: DBDep) -> AskResponse:
    query_embedding = await embed_query(body.question)
    chunks = await hybrid_search(
        db,
        query_text=body.question,
        query_embedding=query_embedding,
        threshold=body.threshold,
        limit=body.max_chunks,
    )
    if not chunks:
        return AskResponse(
            question=body.question,
            answer="I couldn't find any relevant information in the knowledge base to answer this question.",
            sources=[],
        )
    sources = [
        AskSource(
            chunk_id=str(c["id"]),
            document_id=str(c["document_id"]),
            content=c["content"],
            score=c["score"],
        )
        for c in chunks
    ]
    try:
        answer = await answer_question(body.question, chunks)
    except Exception as exc:
        logger.warning("answer_generation_failed", question=body.question[:60], error=str(exc))
        return AskResponse(
            question=body.question,
            answer=(
                "I found relevant document excerpts, but Gemini answer generation is temporarily "
                "unavailable. Please review the sources below."
            ),
            sources=sources,
        )
    return AskResponse(question=body.question, answer=answer, sources=sources)
