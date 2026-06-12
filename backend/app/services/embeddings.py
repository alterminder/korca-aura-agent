import structlog

from app.config import settings
from app.services._http import _post_with_retries, get_gemini_client
from app.services.usage import estimate_tokens, log_gemini_spend

logger = structlog.get_logger()

BATCH_SIZE = 20
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _model_id(model: str) -> str:
    return model.removeprefix("models/")


def _model_name(model: str) -> str:
    model_id = _model_id(model)
    return f"models/{model_id}"


async def generate_embeddings(
    chunks: list[str], *, context: dict | None = None
) -> list[list[float]]:
    """Generate Gemini embeddings for text that will be stored in the graph."""
    if not chunks:
        return []
    return await _gemini_embeddings(chunks, task_type="RETRIEVAL_DOCUMENT", context=context)


async def embed_query(query: str, *, context: dict | None = None) -> list[float]:
    """Embed a single search query using the same Gemini model as AuraDB."""
    embeddings = await _gemini_embeddings([query], task_type="RETRIEVAL_QUERY", context=context)
    return embeddings[0]


async def test_gemini_embedding_api(api_key: str, model: str | None = None) -> list[float]:
    """Call Gemini once for health checks without writing anything to AuraDB."""
    embeddings = await _gemini_embeddings(
        ["Korca Gemini embedding health check"],
        task_type="RETRIEVAL_QUERY",
        api_key=api_key,
        model=model or settings.gemini_embedding_model,
    )
    return embeddings[0]


async def _gemini_embeddings(
    chunks: list[str],
    *,
    task_type: str,
    api_key: str | None = None,
    model: str | None = None,
    context: dict | None = None,
) -> list[list[float]]:
    """Call Gemini batchEmbedContents in batches and preserve input order."""
    resolved_api_key = api_key or settings.gemini_api_key
    if not resolved_api_key:
        raise ValueError("GEMINI_API_KEY is required for embeddings")

    resolved_model = _model_name(model or settings.gemini_embedding_model)
    model_id = _model_id(resolved_model)
    endpoint = f"{GEMINI_API_BASE}/{_model_name(resolved_model)}:batchEmbedContents"
    ctx = context or {}

    all_embeddings: list[list[float]] = []
    async with get_gemini_client() as client:
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            try:
                response = await _post_with_retries(
                    client,
                    endpoint,
                    headers={
                        "x-goog-api-key": resolved_api_key,
                        "Content-Type": "application/json",
                    },
                    payload={
                        "requests": [
                            {
                                "model": resolved_model,
                                "content": {"parts": [{"text": text}]},
                                "taskType": task_type,
                            }
                            for text in batch
                        ]
                    },
                    timeout=60.0,
                )
            except Exception:
                await log_gemini_spend(
                    kind="embed", model=model_id, requests=len(batch), result="error", **ctx
                )
                raise
            data = response.json()
            all_embeddings.extend([item["values"] for item in data.get("embeddings", [])])
            await log_gemini_spend(
                kind="embed",
                model=model_id,
                requests=len(batch),
                input_tokens=estimate_tokens(batch),
                result="ok",
                **ctx,
            )

    if len(all_embeddings) != len(chunks):
        raise ValueError(
            f"Gemini returned {len(all_embeddings)} embeddings for {len(chunks)} inputs"
        )
    return all_embeddings
