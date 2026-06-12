# Environment Variables

Local dev uses a `.env` file; in production the same variables are injected by a
secrets manager. `.env.example` is a starter template with the common settings;
the full set below mirrors the fields in `backend/app/config.py`.

```bash
# App
KORCA_ENV=development
KORCA_DEBUG=true
KORCA_LOG_LEVEL=INFO
KORCA_AUTH_PASSWORD=
KORCA_AUTH_COOKIE_SECRET=
KORCA_AUTH_COOKIE_SECRET_FILE=
KORCA_AUTH_COOKIE_SECURE=false
CORS_ALLOWED_ORIGINS=["http://localhost:5173", "http://localhost:3000"]

# Set KORCA_AUTH_PASSWORD in deployed environments. Leaving it empty bypasses auth for local development and tests.
# Docker Compose users normally set only KORCA_AUTH_PASSWORD. Leave KORCA_AUTH_COOKIE_SECRET_FILE empty unless overriding the generated-secret path.
# Compose supplies /data/secrets/auth-cookie-secret by default and stores it on a named volume across restarts.

# Neo4j Aura
NEO4J_URI_AURA=
NEO4J_USER_AURA=
NEO4J_PASS_AURA=
NEO4J_DATABASE_AURA=

# Gemini document processing, generation, and embeddings
GEMINI_API_KEY=
GEMINI_GENERATION_MODEL=gemini-2.5-flash
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001

# Aura agent
AURA_CLIENT_ID=
AURA_CLIENT_SECRET=
AURA_AGENT_ENDPOINT=
AURA_TRACE_ENABLED=false
AURA_TRACE_SAMPLE_RATE=1.0
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://cloud.langfuse.com

# Redis
REDIS_URL=redis://localhost:6379

# Teamwork Desk (only needed for live ticket import/sync)
TEAMWORK_API_KEY=
TEAMWORK_SUBDOMAIN=<subdomain>.teamwork.com
TEAMWORK_FALLBACK_AGENT_EMAIL=
TEAMWORK_STAGING_EXPERT_NAME=
TEAMWORK_STAGING_EXPERT_EMAIL=
TEAMWORK_SUBJECT_BLOCKLIST=
TEAMWORK_PERSONAL_DOMAINS=gmail.com,yahoo.com,hotmail.com,outlook.com,icloud.com,me.com,protonmail.com

# File storage
UPLOAD_MAX_SIZE_MB=50
TEMP_UPLOAD_PATH=/tmp/korca-uploads
PDF_STORAGE_PATH=/data/pdfs
BACKUP_STORAGE_PATH=/data/pdfs/backups
```
