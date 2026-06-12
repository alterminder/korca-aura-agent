# AGENTS.md

Shared instructions for AI assistants working on Korca Aura. This is the canonical
guide; Claude Code loads it through `CLAUDE.md`, which imports this file.

## Project Invariants

- Korca Aura connects only to **Neo4j Aura**. Do not add a local Neo4j fallback.
- Ticket routing uses the Neo4j Aura-hosted triage agent client in `backend/app/services/aura_agent.py`.
- Basic password auth is required for the app. Keep it simple: one shared password, signed HttpOnly cookie sessions, no SSO/provider integrations unless explicitly requested.
- Keep changes minimal, find root causes for bugs, and verify before reporting a task done.

## Stack

| Area | Technology |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Pydantic |
| Frontend | TypeScript, React 18, Vite, TailwindCSS |
| Database | Neo4j Aura |
| LLM | Gemini generation |
| Document processing | PDF text extraction, Gemini generation, Gemini embeddings |
| Async work | Celery with Redis |
| Routing agent | Neo4j Aura-hosted agent |

## Where To Start

- Backend work: read `backend/AGENTS.md`.
- Frontend work: read `frontend/AGENTS.md`.
- Code conventions (canonical patterns): `agent_docs/conventions.md`.
- Commands and test guidance: `agent_docs/commands.md` and `agent_docs/testing.md`.
- API route map: `agent_docs/api-endpoints.md`.
- Neo4j/Cypher guidance: `agent_docs/database.md`.
- PDF ingestion pipeline: `agent_docs/pdf-pipeline.md`.
- Aura agent tools + prompt: `docs/TOOLS.md`.

## Workflow

- For non-trivial tasks, plan first and update the plan if new facts invalidate it.
- Before editing, inspect the relevant files and follow existing patterns.
- Prefer targeted tests or checks that match the changed area over broad suites that add noise.
- Do not revert unrelated user changes in the working tree.

## Commit & PR

- Branch off `main`; open focused PRs against `main` (don't push to `main`).
- Make the relevant checks green before pushing:
  - Backend (run in `backend/`): `ruff check app`, `mypy app`, `pytest`
  - Frontend (run in `frontend/`): `npm run typecheck`, `npm run lint`, `npm run build`
- Never commit secrets, `.env` files, generated build output, or dependency dirs.
