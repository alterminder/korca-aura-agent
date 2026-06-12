# Roadmap

Non-blocking ideas and improvements, consolidated from earlier planning notes and
the codebase review. Nothing here is required to run Korca Aura — it's a backlog,
roughly grouped, not a committed schedule.

## Features

- **In-app Gemini spend dashboard** — `/api/usage/spend` endpoint + a Usage page (Redis spend counters already accrue in `services/usage.py`).
- **Connector abstraction** — a generic ticket-ingest interface so sources beyond Teamwork Desk (Jira, ServiceNow, …) can feed the graph.

## Routing & data quality

- Team/department-aware routing as an additional signal.
- Admin expert email merge/change action: move or merge an existing Korca expert
  into a new email address when the corresponding Teamwork Desk agent changes
  email, preserving skills, manager links, document links, and ticket history.
- Deterministic ticket-content cleanup before embedding (strip signatures/boilerplate).
- Search query cache for repeated semantic lookups.
- Surface Langfuse routing scores for offline evaluation.
- Prompt-injection hardening on ticket text fed to the agent.

## Testing

- Broaden frontend component coverage for main pages, drawers, and mutation flows.
- Optional CI integration tests against a Neo4j Aura test database.

## Infrastructure & resilience

- Automated backup as a Celery beat task (today backup is a manual API call).
- Circuit breaker for external API calls (Gemini / Teamwork / Aura) to fail fast when a dependency is down.
- Changelog + schema/migration history.
- API versioning (`/api/v1/`) — low priority for a single-consumer tool.

## Performance

- Sync-loop parallelisation with a bounded `asyncio.gather`.

## Tooling

- Migrate ESLint to flat config when upgrading to ESLint 9.
