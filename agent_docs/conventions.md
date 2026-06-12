# Code Conventions

Canonical patterns for Korca Aura. When two ways of doing something exist in the
tree, **this document names the winner.** New code follows these; existing code is
aligned opportunistically.

Derived from a whole-repo consistency audit (2026-06-03). Tooling already
enforces formatting, import order, and lint — these are the conventions tools
*can't* check.

---

## Backend (Python / FastAPI)

### Layering

```
api/routes/   thin HTTP layer — parse input, call a service, return a model
services/     business logic, external calls (Teamwork, Gemini, Redis)
db/queries/   Neo4j Cypher only
models/       shared Pydantic models
```

Routes stay thin. Push logic into `services/`; push Cypher into `db/queries/`.

### Route responses — always a Pydantic model

Every `@router` handler returns a `BaseModel` (or `list`/union thereof), **never
a raw `dict`/`list[dict]`**. This is already mandated in `backend/AGENTS.md`.

```python
# ✅ canonical
@router.get("/teamwork/routing-mode")
async def get_teamwork_routing_mode() -> RoutingModeResponse: ...

# ❌ avoid
async def list_users(db: DBDep) -> list[dict[str, Any]]: ...
```

- Define response models in the route file (small, route-specific) or `app/models/` (shared).
- Suffix convention: `*Response` for outputs, `*Request` for bodies, `*Item` for list elements.
- **Only exception:** passthrough of an external API whose shape we don't own → `dict[str, Any]` is acceptable as a documented minimum.

### Error handling — two accepted tiers (by origin)

Errors surface one of two ways depending on where they originate. **Both are
canonical** — pick by layer:

- **Route-level / HTTP concerns** (malformed request, a missing field at the API
  boundary, a check that never reaches a service): raise `HTTPException` directly
  in the handler. This is idiomatic FastAPI and the common case.
- **Service / business / infra errors** (not-found, conflict, validation deep in
  logic, Neo4j unavailability): raise a domain exception (`app/exceptions.py`) and
  let the global handler in `app/main.py` map it to a status. This keeps services
  HTTP-agnostic, so the same error maps consistently wherever it's called.

```python
# ✅ route-level input check (in the handler)
raise HTTPException(status_code=422, detail="name and email are required")

# ✅ service-layer business error (mapped by the global handler)
raise DomainValidationError("name and email are required")   # -> 400
raise TicketNotFoundError(ticket_id)                          # -> 404
```

Soft preference: in a **service**, prefer a domain exception over a bare
`ValueError` so it maps to a sensible status instead of surfacing as a 500.

Domain exception → status map (`app/exceptions.py` + `app/main.py`):

| Exception | Status |
| --- | --- |
| `DomainValidationError` | 400 |
| `TicketNotFoundError` | 404 |
| `SyncConflictError`, `SyncNotBootstrappedError` | 409 |
| `FileOversizedError` | 413 |
| `AuraAgentError` | 502 |
| Neo4j `ServiceUnavailable` / `TransientError` | 503 |

### Logging — structlog, event-name first

```python
import structlog
logger = structlog.get_logger()

logger.warning("domain_error", path=request.url.path, exc_type=type(exc).__name__)
```

- Variable is always `logger`. Do **not** use stdlib `logging.getLogger`.
- First arg is a snake_case event name; context as `key=value` kwargs.

### Tests

- `pytest` with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed for new tests, but the existing explicit marks are fine).
- **Async test doubles: prefer `unittest.mock.AsyncMock`** — `monkeypatch.setattr(target, AsyncMock(return_value=...))` (or `side_effect=`).
- Only when a stub needs hand-written logic (assertions, branching, counters) use an `async def fake_*` and wrap returns with the `_async_value(...)` helper so it passes Sonar S7503. For raise-only stubs, add `await asyncio.sleep(0)` before the raise.

---

## Frontend (TypeScript / React)

### Data fetching — api client + react-query

The rule is **no raw `fetch()` in components/pages — all HTTP goes through the
typed client in `src/api/client.ts`.** The default consumer is
`@tanstack/react-query`. (Documented in `frontend/AGENTS.md`.)

```ts
// ✅ canonical
const { data } = useQuery({
  queryKey: ['teamwork-routing-mode'],
  queryFn: api.import.teamworkRoutingMode,
})

// ❌ avoid — raw fetch bypasses the typed client + cache
const res = await fetch('/api/clients')
```

- Mutations: prefer `useMutation` + `queryClient.invalidateQueries` for page/shared mutations. Direct `await api.*` handlers are acceptable for local one-off actions (the majority pattern today — ~27 direct vs 8 `useMutation`), **as long as they invalidate or refetch any affected queries** afterward.
- `queryKey` is a kebab/string array describing the resource.
- **SSE-backed local state:** when a list is seeded by an initial load and then merged with live `EventSource` updates into local `useState` (e.g. notifications), the initial load may run in a `useEffect` through the typed client instead of `useQuery`. react-query owns one snapshot; merging a stream into it is awkward, so local state is the cleaner owner here. Still **no raw `fetch()`** — go through `api.*`.
- **Streaming exception:** SSE/streaming endpoints (e.g. `invoke-stream`) may use raw `fetch`/`EventSource` directly — react-query doesn't model streams.

### Styling — Tailwind palette first

Use Tailwind's built-in color utilities wherever they fit (`slate`, `neutral`,
`emerald`, `red`, etc.). Use the `app` palette only for reusable product
semantics (`app-panel`, `app-border`, `app-nav-text`, `app-accent`).

**No hardcoded hex/rgb arbitrary color utilities in `className`.** If Tailwind
has a close built-in match, use it. Add an `app.*` token only when the color is a
named app semantic or must stay consistent across many unrelated components.

```tsx
// ✅                // ❌
text-slate-950       text-[#0d0d0d]
bg-neutral-950       bg-[#0d0d0d]
border-slate-950/30  text-[rgb(100,116,139)]
bg-app-panel
```

### Components & types

- **Named exports**: `export function ComponentName()`. Default export only for the `App` root.
- Component files **PascalCase** (`TicketRoutingSection.tsx`); hooks `useX.ts` in `src/hooks/`; non-component helpers camelCase (`ticketRoutingHelpers.ts`).
- **`interface`** for object/prop shapes; `type` only for unions/aliases.
- Shared types live in `src/types/`.

---

## Tooling (already enforced — don't fight it)

| Stack | Format / lint | Types |
| --- | --- | --- |
| Backend | `ruff check app` / `ruff format app` (line-length 100) | `mypy app` |
| Frontend | `npm run lint` (eslint, max-warnings 0) | `npm run typecheck` |

Import ordering is handled by ruff (`I`) and eslint — never hand-order imports.

---

## Non-goals / accepted variations

Considered during the consistency audit (2026-06-03) and deliberately left as-is:

- **Error-handling consolidation is a non-goal.** The two-tier split above is
  intentional; there is no plan to migrate the inline `HTTPException`s in routes to
  domain exceptions. The only soft preference is choosing a domain exception over a
  bare `ValueError` in a service when you're already editing that code.
- **Response-model suffixes `*Result` and `*Response`** both appear and are
  semantically distinct (an operation result vs an endpoint response) — fine to keep.
- **URL path params are snake_case** (`/{ticket_id}`); static path segments are
  kebab (`/route-aura`) — conventional FastAPI.
- **Direct `await api.*` mutation handlers** coexist with `useMutation` (see
  "Data fetching") — both accepted.
