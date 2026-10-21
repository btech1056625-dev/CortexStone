# Development setup and integration contract

## Local development

Requirements: Python 3.12 or 3.13, Docker Desktop with its Linux engine running, and Docker Compose v2.

1. Copy `.env.example` to `.env`. The sample password is for local development only. If you change it, use letters and numbers so it can be placed safely in the Compose database URL.
2. Start the database and API:

   ```powershell
   Copy-Item .env.example .env
   docker compose up --build
   ```

   The API is available at `http://localhost:8000`; PostgreSQL is available to host tools at `localhost:5432`.
3. Check liveness and readiness:

   ```powershell
   Invoke-RestMethod http://localhost:8000/health/live
   Invoke-RestMethod http://localhost:8000/health/ready
   ```

4. Open the versioned API docs at `http://localhost:8000/api/v1/docs`.
5. Stop the services with `docker compose down`. The named `postgres_data` volume preserves database data. `docker compose down --volumes` removes that local data.

To run the API from the host instead, install the project and development tools, start only PostgreSQL with `docker compose up -d db`, then set `DATABASE_URL` in the shell to `postgresql://cortexstone:local-dev-only@localhost:5432/cortexstone` and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --editable ".[dev]"
py -m uvicorn cortexstone.api.main:app --reload
```

Run checks with `ruff check .`, `ruff format --check .`, and `pytest`. Compose reads `.env` for database and port settings; the host-run API reads `DATABASE_URL` from its process environment.

## API and integration conventions

- Put product endpoints under `/api/v1`. Keep platform probes `/health/live` and `/health/ready` unversioned so deployment tooling can use stable paths.
- Use JSON, typed Pydantic request/response models, and UTC ISO-8601 timestamps. Do not return ORM or provider objects directly.
- Use a consistent error envelope: `{"error":{"code":"...","message":"..."},"request_id":"..."}`. Do not return stack traces, credentials, or raw provider errors to clients.
- Every response includes a server-generated `X-Request-ID`. Include that ID in operational logs when reporting a request failure; do not treat a client-supplied ID as trusted.
- Keep route handlers thin: validate transport data, call an application service, and translate its result. Routes and model output must not bypass policy, approvals, or restricted tool execution.
- Scope user-owned data by the authenticated principal in every query. Authentication is not implemented by this bootstrap; do not expose user-data routes until it is.
- Keep database access behind repositories/services as they are introduced. Coordinate schema and API changes with their owners before merging; update OpenAPI schemas and tests in the same change.
- Return truthful status codes. Use `503` for readiness when a required dependency is unavailable; liveness must not depend on PostgreSQL.

## Current bootstrap endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health/live` | Process liveness |
| GET | `/health/ready` | PostgreSQL connectivity check |
| GET | `/api/v1/health` | Versioned API status |
| GET | `/api/v1/docs` | Interactive OpenAPI documentation |
| GET | `/api/v1/openapi.json` | OpenAPI document |

The Compose database uses the PostgreSQL 16 pgvector image and enables the `vector` extension on first initialization. Database migrations and application data models are not part of this bootstrap yet.
