# Stage 1: Build frontend
FROM node:24-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Compile Python dependencies (needs build-essential for C extensions)
FROM python:3.11-slim AS python-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Use the same WORKDIR as the runtime stage so venv-internal paths stay valid
# when the venv directory is copied across stages.
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 3: Final runtime image (no compiler toolchain)
FROM python:3.11-slim

RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=python-builder /app/.venv /app/.venv
COPY backend/app/ app/
COPY --from=frontend-builder /frontend/dist /app/static

RUN useradd -m -u 1001 appuser \
    && mkdir -p /data/pdfs /data/secrets /tmp/korca-uploads \
    && chown -R appuser:appuser /app /data /tmp/korca-uploads

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
