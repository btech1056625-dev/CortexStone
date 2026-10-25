# Development setup and integration contract

## Local development

Requirements: Python 3.12 or 3.13, Docker Desktop with its Linux engine running, and Docker Compose v2.

1. Copy `.env.example` to `.env`. The sample password is for local development only. If you change it, use letters and numbers so it can be placed safely in the Compose database URL.
2. Set `CORTEXSTONE_AUTH_ISSUER`, `CORTEXSTONE_AUTH_AUDIENCE`, and `CORTEXSTONE_AUTH_JWKS_URL` in `.env` to the HTTPS issuer, API audience, and signing-key endpoint for your OIDC provider. The API accepts RS256 bearer access tokens with valid `iss`, `aud`, `exp`, and non-empty `sub` claims. All three settings are required together; with them unset, protected routes fail closed with `503`.
3. Start the database and API:

   ```powershell
   Copy-Item .env.example .env
   docker compose up --build
   ```

   The API is available at `http://localhost:8000`; PostgreSQL is available to host tools at `localhost:5433` by default.
4. Apply the database schema and required PostgreSQL `vector` extension:

   ```powershell
   docker compose exec api python -m alembic upgrade head
   ```

   Migrations are versioned in `src/cortexstone/db/migrations` and are not applied automatically at API startup.
5. Check liveness and readiness:

   ```powershell
   Invoke-RestMethod http://localhost:8000/health
   Invoke-RestMethod http://localhost:8000/ready
   ```

   The existing `/health/live` and `/health/ready` paths remain compatibility aliases.

6. Open the versioned API docs at `http://localhost:8000/api/v1/docs`.
7. Stop the services with `docker compose down`. The named `postgres_data` volume preserves database data. `docker compose down --volumes` removes that local data.

To run the API from the host instead, install the project and development tools, start only PostgreSQL with `docker compose up -d db`, then set `DATABASE_URL` in the shell to `postgresql://cortexstone:local-dev-only@localhost:5433/cortexstone` and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --editable ".[dev,postgres,embeddings]"
py -m alembic upgrade head
py -m uvicorn cortexstone.api.main:app --reload
```

Run checks with `ruff check .`, `ruff format --check .`, and `pytest`. Compose reads `.env` for database and OIDC settings; the host-run API reads them from its process environment. `GET /api/v1/me` returns the verified subject as `id`, its optional token name (or subject fallback) as `display_name`, and `authenticated: true`. The public memory MVP routes are `GET/POST /api/v1/memories`, `GET /api/v1/memories/{memory_id}`, and `DELETE /api/v1/memories/{memory_id}`. List returns `{items, total, limit, offset}`; public memory objects expose only `id`, `content`, `memory_type`, `source`, `confidence`, `created_at`, and `updated_at`. Create accepts only `content` and `memory_type`, sets source to `user` and confidence to `1.0`, and rejects extra fields such as `owner_id`. Memory ownership always comes from the verified token subject; an inaccessible memory ID returns `404`, and deletion returns `204` with no body. Memory search, export, and editing are not part of the public frontend contract and have no HTTP routes. Action validation uses the authenticated subject and continues to deny actions unless a backend permission grant is configured. The Alembic migration creates the `memory_items` table and enables pgvector's `vector` extension; PostgreSQL 16 provides `gen_random_uuid()` without an additional extension. Migrations use `DATABASE_URL` and convert standard `postgresql://` URLs to SQLAlchemy's asynchronous asyncpg dialect. The API likewise converts standard `postgresql://` URLs, creates an application-scoped engine and session factory, and disposes the engine on shutdown. Each request receives a closed session, and exceptions roll back the active transaction. `/ready` checks the configured database through that SQLAlchemy engine; `/health` does not require PostgreSQL. The prior `/health/live` and `/health/ready` routes remain non-contract compatibility aliases.
Run checks with `ruff check .`, `ruff format --check .`, and `pytest`. Compose reads `.env` for database and OIDC settings; the host-run API reads them from its process environment. The API uses the existing BGE embedding provider for memory creation and persists its 384-dimensional vectors through the SQLAlchemy memory repository into pgvector. The provider loads FastEmbed and its model lazily when the first memory is created. `GET /api/v1/me` returns the verified subject as `id`, its optional token name (or subject fallback) as `display_name`, and `authenticated: true`. The public memory MVP routes are `GET/POST /api/v1/memories`, `GET /api/v1/memories/{memory_id}`, and `DELETE /api/v1/memories/{memory_id}`. List returns `{items, total, limit, offset}`; public memory objects expose only `id`, `content`, `memory_type`, `source`, `confidence`, `created_at`, and `updated_at`. Create accepts only `content` and `memory_type`, sets source to `user` and confidence to `1.0`, and rejects extra fields such as `owner_id`. Memory ownership always comes from the verified token subject; an inaccessible memory ID returns `404`, and deletion returns `204` with no body. Memory search, export, and editing are not part of the public frontend contract and have no HTTP routes. Action validation uses the authenticated subject and continues to deny actions unless a backend permission grant is configured. The Alembic migration creates the `memory_items` table and enables pgvector's `vector` extension; PostgreSQL 16 provides `gen_random_uuid()` without an additional extension. Migrations use `DATABASE_URL` and convert standard `postgresql://` URLs to SQLAlchemy's asynchronous asyncpg dialect. The API likewise converts standard `postgresql://` URLs, creates an application-scoped engine and session factory, and disposes the engine on shutdown. Each request receives a closed session, and exceptions roll back the active transaction. `/ready` checks the configured database through that SQLAlchemy engine; `/health` does not require PostgreSQL. The prior `/health/live` and `/health/ready` routes remain non-contract compatibility aliases.

## API and integration conventions

- Put product endpoints under `/api/v1`. The frontend contract uses `/health` and `/ready`; `/health/live` and `/health/ready` remain compatibility aliases.
- Use JSON, typed Pydantic request/response models, and UTC ISO-8601 timestamps. Do not return ORM or provider objects directly.
- Use a consistent error envelope: `{"error":{"code":"...","message":"..."},"request_id":"..."}`. Do not return stack traces, credentials, or raw provider errors to clients.
- Every response includes a server-generated `X-Request-ID`. Include that ID in operational logs when reporting a request failure; do not treat a client-supplied ID as trusted.
- Keep route handlers thin: validate transport data, call an application service, and translate its result. Routes and model output must not bypass policy, approvals, or restricted tool execution.
- Scope user-owned data by the verified OIDC token subject in every query. Never accept identity or owner scope from request headers other than the bearer token or from request payloads.
- Keep database access behind repositories/services as they are introduced. Coordinate schema and API changes with their owners before merging; update OpenAPI schemas and tests in the same change.
- Return truthful status codes. Use `503` for readiness when a required dependency is unavailable; liveness must not depend on PostgreSQL.

## Chat payload schemas

`POST /api/v1/chat` delegates to `application/chat/ChatService` after resolving the authenticated `PolicyPrincipal`. The use case retrieves at most five memories for the verified subject, limits context to normal-sensitivity records, and excludes deleted, cross-owner, and unapproved skill records before formatting escaped, bounded memory context. For personal recall, model instructions require citations from stored source references and timestamps, distinguish inferences as uncertain, and prohibit unsupported personal claims. The existing `AgentOrchestrator` generates the structured application `ChatResult`, which is converted to the transport `ChatResponse`; the server sets `conversation_id` from the request and never executes proposed actions. The conversation ID is opaque and echoed only; the endpoint does not persist or retrieve chat history. Requests require a non-blank message (up to 10,000 characters), may include an opaque conversation ID, and reject unknown fields. Responses echo that ID when supplied, require a non-blank answer or at least one typed proposed action, limit answers to 20,000 characters and action proposals to three per turn, and reject unknown fields. They reuse the agent layer's `ProposedAction` schema, which validates bounded tool names, targets, and purposes and forbids model-supplied authorization fields. Agent plans allow up to five steps internally; the API's three-proposal cap follows the per-turn integration contract. Chat requires a configured `NEBIUS_API_KEY`; without it the route returns `503` rather than using a mock or fallback model.

## Backend action policy

`PolicyEngine` in `src/cortexstone/security/policy/service.py` evaluates typed proposals against a server-owned tool registry and backend-resolved principal grants. It fails closed for unknown tools, targets outside either allowlist, missing grants, and missing, unexpected, or non-JSON arguments. Grants are exact tool/scope/target combinations; target matching does not use wildcard patterns. Read-only, low-risk actions may be allowed; write actions and medium/high-risk actions require trusted, unexpired approval evidence bound to the exact target and SHA-256 hash of the tool and canonical arguments. The model cannot supply this evidence.

The `POST /api/v1/actions/validate` endpoint uses FastAPI dependencies to obtain the app-scoped policy engine and verified OIDC principal. It accepts no approval evidence and never executes actions; the current principal has no permission grants, so proposals remain denied until a backend permission-grant integration is configured. Permission persistence/revocation, approval storage, audit logging, per-tool argument schemas, and revalidation immediately before execution remain integration work.

Configure exact `notes.search` targets with the comma-separated `CORTEXSTONE_POLICY_NOTES_SEARCH_TARGETS` environment variable (for example, `notes/personal`). It defaults to empty, which registers no tools and fails closed. Only targets configured by the backend are considered; request payloads cannot configure policy.

All actual tool calls must go through `ToolRunner.execute(principal, action)` in `src/cortexstone/tools/runner/service.py`. The runner resolves trusted approval evidence (when configured), evaluates the action immediately before dispatch, and invokes only a registered executor when the decision is `ALLOW`. Direct connector calls from application code bypass this guarantee and must not be introduced. No concrete tool executors are registered yet.

## Current bootstrap endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process liveness |
| GET | `/ready` | PostgreSQL connectivity check |
| GET | `/health/live` | Compatibility alias for process liveness |
| GET | `/health/ready` | Compatibility alias for readiness |
| GET | `/api/v1/me` | Authenticated OIDC subject |
| POST | `/api/v1/chat` | Authenticated chat with permitted owner memory context |
| GET/POST | `/api/v1/memories` | Owner-scoped memory list/create |
| GET/DELETE | `/api/v1/memories/{memory_id}` | Owner-scoped memory read/forget |
| POST | `/api/v1/actions/validate` | Validate a typed action proposal; does not execute it |
| GET | `/api/v1/docs` | Interactive OpenAPI documentation |
| GET | `/api/v1/openapi.json` | OpenAPI document |

The Compose database uses the PostgreSQL 16 pgvector image and enables the `vector` extension on first initialization. Apply the Alembic migrations before using the memory API.
