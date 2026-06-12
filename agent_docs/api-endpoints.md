# API Endpoints

## Auth (`/api/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/auth/me` | Current cookie auth state |
| POST | `/api/auth/login` | Start signed cookie session with shared password |
| POST | `/api/auth/logout` | Clear signed cookie session |

## Health & Stats (`/api`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Public health check |
| GET | `/api/health/db` | Neo4j connectivity check |
| GET | `/api/stats` | Graph node/edge summary |
| GET | `/api/stats/recent-activity` | Recent Aura routing events |
| GET | `/api/stats/expert-load` | Per-expert ticket load |
| GET | `/api/stats/client-load` | Per-client ticket load |
| GET | `/api/stats/needs-review` | Count of staged tickets |

## Documents (`/api/documents`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/documents/upload` | Upload PDF (enqueues Celery job) |
| GET | `/api/documents` | List all documents |
| GET | `/api/documents/{id}` | Get document |
| GET | `/api/documents/{id}/status` | SSE upload/processing status |
| GET | `/api/documents/{id}/download` | Download original PDF |
| DELETE | `/api/documents/{id}` | Delete document |
| GET | `/api/documents/{id}/experts` | List experts linked to document |
| POST | `/api/documents/{id}/experts` | Link an expert to document |
| DELETE | `/api/documents/{id}/experts` | Unlink an expert from document |

Response models: `GET /api/documents` returns `list[DocumentResponse]` (with
`experts`) and `GET /api/documents/{id}` returns `DocumentResponse` (with embedded
`chunks` as `DocumentChunkItem`). Compatible with the frontend `Document` type, but
more tolerant — backend fields are nullable, and embedded chunks omit `document_id`.

## Users / Experts (`/api/users`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users` | List all users |
| POST | `/api/users` | Create user |
| GET | `/api/users/{id}` | Get user profile |
| PATCH | `/api/users/{id}/profile` | Update user profile |
| DELETE | `/api/users/{id}` | Delete user |
| POST | `/api/users/{id}/generate-skills` | LLM-generate skill tags from ticket history |
| GET | `/api/users/compare` | Compare two users side-by-side |

Response models: `UserResponse`, `UserDetailResponse`, `ExpertComparisonResponse`, and
`GenerateSkillsResponse`.

## Search & Routing (`/api/search`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/search` | Hybrid semantic + fulltext search |
| POST | `/api/search/ask` | RAG Q&A over SOPs |

## Clients (`/api/clients`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clients` | List all client organisations |
| GET | `/api/clients/{domain}` | Get client detail |
| POST | `/api/clients/{domain}/link` | Link client to parent org |
| DELETE | `/api/clients/{domain}/link` | Unlink client from parent |

Response models: `GET /api/clients` returns `list[ClientResponse]` and
`GET /api/clients/{domain}` returns `ClientDetailResponse` (adds `agents` and
embedded `tickets` as `ClientTicketItem`). Compatible with the frontend `Client`
type, but more tolerant — backend fields such as `name` are nullable.

## Import — Teamwork (`/api/import/teamwork`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/import/teamwork` | SSE stream — run Teamwork import |
| GET | `/api/import/teamwork/filters` | Available filter options (agents, statuses) |
| GET | `/api/import/teamwork/tickets` | List imported Teamwork tickets |
| GET | `/api/import/teamwork/tickets/count` | Count imported Teamwork tickets |
| DELETE | `/api/import/teamwork/tickets` | Clear imported Teamwork tickets |
| GET | `/api/import/teamwork/routing-mode` | Get Teamwork routing mode (`manual`, `auto_comment`, `auto_assign`) + `staging_expert_configured` flag (`bool(TEAMWORK_STAGING_EXPERT_EMAIL)`) |
| PUT | `/api/import/teamwork/routing-mode` | Persist Teamwork routing mode |
| GET | `/api/import/teamwork/auto-sync` | Get auto-sync enablement and interval |
| PUT | `/api/import/teamwork/auto-sync` | Persist auto-sync enablement and interval |
| GET | `/api/import/teamwork/sync-state` | Get Teamwork `updatedAt` sync cursor state |
| POST | `/api/import/teamwork/sync/bootstrap` | Initialize Teamwork update cursor to current time |
| POST | `/api/import/teamwork/sync-now` | Manually sync Teamwork tickets changed after the cursor |
| GET | `/api/import/teamwork/purge-blocked/preview` | Preview tickets that would be purged |
| POST | `/api/import/teamwork/purge-blocked` | Purge blocked/spam tickets |
| GET | `/api/import/teamwork/status` | Import run status |
| GET | `/api/import/teamwork/progress` | SSE stream of import progress events |
| POST | `/api/import/teamwork/tickets/{id}/reimport` | Re-import a single ticket |
| POST | `/api/import/teamwork/tickets/{id}/sync` | Re-fetch and sync a single ticket through the normal sync path |

Response models: `/teamwork/filters` → `TeamworkFilterOptionsResponse`;
`/teamwork/tickets` → `list[TicketResponse]` (reuses the tickets model — same
`list_tickets` query); `/teamwork/auto-sync` (GET/PUT) → `TeamworkAutoSyncResponse`;
`/teamwork/sync/bootstrap` → `TeamworkSyncStateResponse`.

## Import — Tickets & Routing (`/api/import/tickets`, `/api/import/routing`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/import/tickets` | List all imported tickets |
| GET | `/api/import/tickets/{id}` | Get ticket detail |
| POST | `/api/import/tickets/{id}/route-aura` | Run Aura agent routing and create a `RoutingEvent` |
| POST | `/api/import/tickets/{id}/post-aura-suggestion` | Post latest Aura suggestion as a private Teamwork note |
| POST | `/api/import/tickets/{id}/assign-aura-suggestion` | Assign latest Aura suggested expert in Teamwork |
| POST | `/api/import/tickets/{id}/post-staging-expert` | Post staging expert (from `TEAMWORK_STAGING_EXPERT_NAME/EMAIL`) as a private Teamwork note |
| POST | `/api/import/tickets/{id}/assign-staging-expert` | Assign staging expert (from `TEAMWORK_STAGING_EXPERT_EMAIL`) in Teamwork |
| POST | `/api/import/tickets/{id}/confirm` | Confirm routing suggestion |
| POST | `/api/import/tickets/{id}/reassign` | Reassign to different expert |
| POST | `/api/import/tickets/{id}/promote` | Promote staged ticket to graph |
| DELETE | `/api/import/tickets/{id}` | Delete ticket |
| POST | `/api/import/tickets/bulk-delete` | Bulk delete tickets |
| GET | `/api/import/staged` | List staged (not yet promoted) tickets |
| GET | `/api/import/routing/ai-accuracy` | Aura `RoutingEvent` accuracy against `ASSIGNED_TO` |
| POST | `/api/import/routing/backfill-gate` | Backfill routing gate pass/fail flags |

Response models: `GET /api/import/tickets` returns `list[TicketResponse]` and
`GET /api/import/tickets/{id}` returns `TicketResponse` (compatible with the frontend
`Ticket` type but more tolerant — backend fields are nullable; nested
`routing_suggestions` use `RouteSuggestionResponse`; internal fields such as
`gemini_embedding` are not exposed). `POST .../route-aura` returns
`RouteTicketAuraResponse`; `GET /api/import/routing/ai-accuracy` returns
`RoutingAccuracyResponse` (`evaluated`, `correct`, `accuracy_pct`).

## Aura Agent (`/api/aura`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/aura/agents` | List Aura agents |
| GET | `/api/aura/agents/{agent_id}` | Get Aura agent detail |
| PATCH | `/api/aura/agents/{agent_id}` | Update Aura agent (e.g. toggle `is_private`) |
| POST | `/api/aura/invoke-stream` | SSE stream — invoke Aura agent and stream response |

Response models: the agent endpoints return `AuraAgentResponse` (list/detail/patch).
These proxy the external Neo4j Aura agent API, lightly normalized for the frontend
(compatible with the frontend `AuraAgent` type): unknown upstream fields are preserved
(`extra="allow"`), `null` fields are dropped (`response_model_exclude_none`), and
`tools` always serializes as a list.

## Notifications (`/api/notifications`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/notifications` | List recent system notifications |

## Events (`/api/events`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events/tickets` | SSE stream — pushes `tickets_updated` event when auto-sync finds changed tickets |
| GET | `/api/events/notifications` | SSE stream — pushes new system notification events in real time |

## Backup (`/api/backup`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/backup/create` | Create Neo4j backup |
| GET | `/api/backup/list` | List available backups |
| POST | `/api/backup/upload` | Upload backup file |
| GET | `/api/backup/download/{filename}` | Download backup |
| DELETE | `/api/backup/{filename}` | Delete backup |
| POST | `/api/backup/restore/{filename}` | Restore from backup |

Response models: `GET /api/backup/list` returns `list[BackupResponse]` and
`POST /api/backup/upload` returns `BackupResponse` (`filename`, `created_at`,
`size_kb`, freeform `stats`); `DELETE /api/backup/{filename}` returns
`BackupDeletedResponse`. `create`/`restore` stream SSE; `download` returns a file.

## Error Handling

- Frontend: `react-hot-toast` for user notifications
- API error format: `{"detail": "message"}`
- Backend: structured logging via `structlog`; domain exceptions (`DomainError` subclasses in `app/exceptions.py`) are mapped to HTTP status codes by `domain_error_handler` in `main.py`
