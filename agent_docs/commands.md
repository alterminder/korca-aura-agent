# Common Commands

## Backend

```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
pytest
mypy app
ruff check app
ruff format app
```

## Frontend

```bash
cd frontend
npm install
npm run dev        # port 5173, proxies /api to backend
npm run build
npm run typecheck
npm run lint
```

## Worker (local, outside Docker)

```bash
cd backend
# Celery worker — processes PDF and Aura routing jobs
celery -A app.worker worker --loglevel=info

# Celery beat — fires the Teamwork auto-sync cron every minute
celery -A app.worker beat --loglevel=info

# Combined (dev convenience — single process):
celery -A app.worker worker --beat --loglevel=info
```

## Docker

```bash
docker compose up -d --build

docker compose logs -f api worker beat
docker compose down
```

The compose stack runs four services:

- `api`: FastAPI plus the built frontend on port 8000
- `worker`: Celery worker — PDF OCR, chunking, embeddings, Aura ticket routing
- `beat`: Celery beat — fires the Teamwork auto-sync cron job every minute
- `redis`: Celery broker, result backend, document status store, rate limiter, and pub/sub for SSE push events

PDFs are stored in the named Docker volume `korca-aura_pdfs` and are mounted at
`/data/pdfs` in both the API and worker containers.
