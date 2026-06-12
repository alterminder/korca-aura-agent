import base64
import json
import re
from pathlib import Path

import structlog

from app.config import settings
from app.services._http import GEMINI_API_BASE, _gemini_text, _post_with_retries, get_gemini_client

logger = structlog.get_logger()

PDF_TRANSCRIPTION_PROMPT = """Transcribe this PDF into clean Markdown for a searchable internal knowledge base.

Requirements:
- Preserve headings, numbered steps, tables, code/config values, URLs, and important labels.
- Include concise descriptions of screenshots, diagrams, charts, and forms where they matter.
- Remove page headers/footers only when they are repetitive and not useful.
- Do not summarize. Keep the actionable document content.

Return JSON with this shape:
{"markdown": "..."}
"""


async def extract_with_ocr(pdf_path: str | Path) -> tuple[str, list[dict], int]:
    """
    Use Gemini document understanding to extract searchable Markdown from a PDF.

    Returns: (markdown_text, images, page_count)
    The image list is kept for API compatibility; Gemini extracts visual context inline.
    """
    path = Path(pdf_path)
    pdf_b64 = base64.b64encode(path.read_bytes()).decode()
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
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": "application/pdf",
                                    "data": pdf_b64,
                                }
                            },
                            {"text": PDF_TRANSCRIPTION_PROMPT},
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": {
                        "type": "object",
                        "properties": {
                            "markdown": {"type": "string"},
                        },
                        "required": ["markdown"],
                    },
                },
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()

    text = _gemini_text(data)
    payload = _json_from_text(text)
    md_text = str(payload.get("markdown") or text).strip()
    page_count = _count_pdf_pages(path)

    logger.info(
        "Gemini PDF extraction complete",
        pages=page_count,
        images=0,
        chars=len(md_text),
        model=settings.gemini_generation_model,
    )
    return md_text, [], page_count


async def describe_images(images: list[dict]) -> dict[str, str]:
    """
    No-op kept for the worker pipeline contract.

    Gemini PDF extraction already includes visual context from pages, screenshots,
    tables, and diagrams in the returned Markdown.
    """
    if images:
        logger.debug(
            "Skipping separate image description; Gemini PDF extraction handles visuals",
            images=len(images),
        )
    return {}


def inject_image_descriptions(md_text: str, descriptions: dict[str, str]) -> str:
    """Replace OCR image placeholders with semantic descriptions."""
    for image_id, description in descriptions.items():
        pattern = rf"!\[{re.escape(image_id)}\]\({re.escape(image_id)}\)"
        replacement = f"\n\n**[Image: {image_id}]** {description}\n\n"
        md_text = re.sub(pattern, replacement, md_text)
    return md_text


def chunk_document(content: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """Semantic chunking: headers → paragraphs → sentences."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
    )
    chunks = splitter.split_text(content)
    logger.info("Chunked document", chunks=len(chunks))
    return chunks


def _json_from_text(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _count_pdf_pages(pdf_path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:
        logger.warning("PDF page count failed", path=str(pdf_path), error=str(exc))
        return 0
