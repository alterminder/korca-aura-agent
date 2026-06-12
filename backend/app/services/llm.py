import json
from typing import Any

import structlog

from app.config import settings
from app.services._http import GEMINI_API_BASE, _gemini_text, _post_with_retries, get_gemini_client

logger = structlog.get_logger()

METADATA_PROMPT = """Extract the following from this document and respond in JSON format only:
- title: The document title (string)
- author: Author name or email if mentioned, otherwise null
- summary: 2-3 sentence summary (string)
- topics: List of main topics/keywords (array of strings)
- document_type: One of [sop, guide, policy, reference, other]

Document:
{content}"""


async def extract_metadata(content: str) -> dict[str, Any]:
    """Use Gemini to extract structured metadata from document content."""
    model = settings.gemini_generation_model.removeprefix("models/")
    async with get_gemini_client() as client:
        response = await _post_with_retries(
            client,
            f"{GEMINI_API_BASE}/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": METADATA_PROMPT.format(content=content[:8000])}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "author": {"type": ["string", "null"]},
                            "summary": {"type": "string"},
                            "topics": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "document_type": {
                                "type": "string",
                                "enum": ["sop", "guide", "policy", "reference", "other"],
                            },
                        },
                        "required": ["title", "summary", "topics", "document_type"],
                    },
                },
            },
            timeout=60.0,
        )
        data = response.json()

    metadata = json.loads(_gemini_text(data))
    logger.info(
        "Metadata extracted",
        title=metadata.get("title"),
        doc_type=metadata.get("document_type"),
        topics=len(metadata.get("topics", [])),
        provider="gemini",
        model=settings.gemini_generation_model,
    )
    return metadata


TICKET_SUMMARY_PROMPT = """You are a knowledge base assistant. Extract only the useful technical and operational request content from this support ticket.

Remove all noise: greetings, sign-offs, "thanks for your patience", auto-reply text, email signatures, and any back-and-forth pleasantries.

Return a clean plain-text request summary in one or two sentences.
Describe only what the customer or internal requester needed, reported, or asked for.
Do not include labels, section headings, fix details, agent actions, or whether the ticket was solved.

Ticket subject: {subject}
Ticket status: {status}

Ticket content:
{raw_content}

Summary:"""


async def summarize_ticket(subject: str, raw_content: str, status: str = "open") -> str:
    """Extract a clean request-only summary from raw ticket content using Gemini."""
    summary = await generate_text(
        TICKET_SUMMARY_PROMPT.format(
            subject=subject,
            status=status,
            raw_content=raw_content[:6000],
        ),
        temperature=0.1,
    )
    logger.debug(
        "Ticket summarized",
        subject=subject[:60],
        status=status,
        length=len(summary),
        provider="gemini",
        model=settings.gemini_generation_model,
    )
    return summary


ASK_PROMPT = """You are a knowledge base assistant. Answer the question below using only the provided excerpts from internal documents.

Be concise and direct. If the excerpts don't contain enough information to answer fully, say so. Do not make up information.

Question: {question}

Excerpts:
{context}

Answer:"""


async def generate_expert_skills(
    expert_name: str, ticket_summaries: list[str], max_skills: int = 12
) -> list[str]:
    """Analyse an expert's resolved tickets and return a list of skill tags."""
    samples = "\n\n---\n\n".join(ticket_summaries[:40])
    prompt = f"""You are analysing support tickets resolved by {expert_name} to identify their areas of expertise.

Based on the ticket summaries below, return a JSON array of {max_skills} short skill tags (2-4 words max each) that best describe what this person specialises in. Focus on technical topics, tools, platforms, and recurring problem types. Avoid generic terms like "customer support" or "ticket resolution".

Respond with ONLY a valid JSON array of strings, e.g. ["email deliverability", "api integrations", "wordpress", "dns configuration"]

Tickets:
{samples}"""

    raw = await generate_text(
        prompt,
        temperature=0.1,
        response_mime_type="application/json",
        response_json_schema={
            "type": "array",
            "items": {"type": "string"},
        },
    )
    try:
        parsed = json.loads(raw)
        # Handle both {"skills": [...]} and plain [...]
        if isinstance(parsed, dict):
            parsed = next((v for v in parsed.values() if isinstance(v, list)), [])
        return [str(s).strip().lower() for s in parsed if s][:max_skills]
    except Exception:
        logger.warning("Failed to parse skill cloud response", raw=raw[:200])
        return []


async def answer_question(question: str, chunks: list[dict]) -> str:
    """Synthesize a readable answer from relevant chunks using Gemini."""
    context = "\n\n---\n\n".join(
        f"[Source: {c['document_id']}, score: {c['score']:.0%}]\n{c['content']}" for c in chunks
    )
    model = settings.gemini_generation_model.removeprefix("models/")
    async with get_gemini_client() as client:
        response = await _post_with_retries(
            client,
            f"{GEMINI_API_BASE}/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": ASK_PROMPT.format(question=question, context=context)}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                },
            },
            timeout=60.0,
        )
        data = response.json()

    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    answer = "".join(str(part.get("text", "")) for part in parts).strip()
    logger.info(
        "Question answered",
        question=question[:60],
        sources=len(chunks),
        provider="gemini",
        model=settings.gemini_generation_model,
    )
    return answer


async def generate_text(
    prompt: str,
    *,
    temperature: float = 0.2,
    response_mime_type: str | None = None,
    response_json_schema: dict | None = None,
) -> str:
    """Generate text with Gemini using the app's configured generation model."""
    generation_config: dict[str, Any] = {"temperature": temperature}
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    if response_json_schema:
        generation_config["responseJsonSchema"] = response_json_schema

    model = settings.gemini_generation_model.removeprefix("models/")
    async with get_gemini_client() as client:
        response = await _post_with_retries(
            client,
            f"{GEMINI_API_BASE}/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.gemini_api_key,
                "Content-Type": "application/json",
            },
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": generation_config,
            },
            timeout=60.0,
        )
        data = response.json()

    return _gemini_text(data)
