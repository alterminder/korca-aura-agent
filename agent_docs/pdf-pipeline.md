# PDF Processing Pipeline

Uploads are enqueued as Celery jobs (async, survives pod restarts). Worker runs as a separate process or K8s pod (`app/worker.py`).

Steps per document:

1. Upload → validate + SHA256 dedup check
2. Store original PDF to `/data/pdfs/`
3. Enqueue Celery job -> worker picks up
4. Extract document text with Gemini generation (`gemini-2.5-flash`)
5. Extract structured metadata with Gemini generation
6. Preserve the original uploaded PDF for download and audit
7. Chunk content semantically (headers → paragraphs → sentences) via LangChain `RecursiveCharacterTextSplitter`
8. Generate embeddings with Gemini (`models/gemini-embedding-001`, 3072 dimensions)
9. Store in Neo4j with graph relationships

Upload status is streamed via SSE (`/api/documents/{id}/status`) backed by Redis.

Entry point: `backend/app/services/` — `pdf.py`, `llm.py`, `embeddings.py`
