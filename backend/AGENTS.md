# Backend Guide

Backend code lives in `backend/app/` and tests live in `backend/tests/`.

## Commands

Run commands from `backend/` unless noted otherwise:

```bash
uv sync
uvicorn app.main:app --reload --port 8000
pytest
mypy app
ruff check app
ruff format app
```

Use focused test runs while iterating, then broaden to the relevant package or full backend suite when risk warrants it.

## Architecture Notes

- FastAPI entry point: `app/main.py`.
- API routes: `app/api/routes/`.
- Pydantic models: `app/models/`.
- Neo4j Aura connection and Cypher: `app/db/`.
- Business logic: `app/services/`.
- Celery worker: `app/worker.py` (tasks: `process_document`, `process_aura_routing_ticket`, `poll_teamwork_updates`).
- Aura-hosted routing agent client: `app/services/aura_agent.py`.

PDF uploads are asynchronous: the API enqueues Celery jobs and the worker processes OCR, image descriptions, metadata extraction, embeddings, and Neo4j writes. Original PDFs must remain in `/data/pdfs`.

## Backend Rules

- Use `NEO4J_URI_AURA`, `NEO4J_USER_AURA`, `NEO4J_PASS_AURA`, and `NEO4J_DATABASE_AURA` for graph access.
- Do not introduce local Neo4j fallback behavior.
- Keep Aura agent auth via `AURA_CLIENT_ID` and `AURA_CLIENT_SECRET`; the token is cached in memory.
- Use structured logging patterns already present in the app.
- For API changes, update `agent_docs/api-endpoints.md` when routes or semantics change.
- **All public FastAPI route handlers must return a typed Pydantic `BaseModel` (or a list/union thereof), never a raw `dict` or `list[dict]`.** Define response models in the route file or in `app/models/`. For responses proxied from external APIs where the shape is unknown, use `dict[str, Any]` as a minimum. This ensures OpenAPI schema generation and runtime serialisation validation.
