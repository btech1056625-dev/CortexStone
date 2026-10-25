# Cortexstone Project Review

**Review updated:** 25 October 2026
**Review baseline:** The 24 October 2026 review, updated for PR #22 and current `main`
**Review scope:** Current repository implementation compared with `Documentations/Cortexstone_PRD.md`, `Documentations/Cortexstone_Architecture_HLD_LLD.md`, the agent and design rules, and the current integration specifications.

## Executive summary

Cortexstone has an authenticated memory-and-chat backend slice and an API-connected React/Vite dashboard, including the work merged in PR #22. The backend provides OIDC identity, owner-scoped memory routes, PostgreSQL/pgvector migrations and persistence wiring, BGE embeddings and retrieval, authenticated chat through the agent orchestrator/model adapter, and policy-only action validation. The dashboard defaults to live mode and calls the implemented health, identity, chat, action-validation, and memory routes. It accepts a bearer token in page memory; it does not implement sign-in or token issuance. Its explicit demo mode retains simulated responses, while unsupported live routes are reported unavailable.

The implementation follows the **intended architecture direction** well: a modular monolith, replaceable model adapters, typed action proposals, fail-closed authorization, explicit owner-scoped memory operations, and separation between policy decisions and tool execution. The current stage is an **integrated backend vertical slice with a connected dashboard, not the completed MVP described in the PRD**. No live PostgreSQL/OIDC/model deployment or deployment rehearsal has been documented.

Important remaining work includes live acceptance of persistence and chat, dashboard checks in CI, durable permission/approval state, registered production connector executors, verified action outcomes, durable jobs and scheduling, Telegram, Guardian scanning, and deployment. Authentication is implemented with configured OIDC and remains fail-closed when unavailable. The dashboard currently requires a valid token to be pasted into Settings. The Nebius model adapter is wired to chat when its API key is configured; live credentials, quota, model availability, PostgreSQL, and deployment have not been verified.

## Implementation status at a glance

| Area | Current state | Assessment against plan |
|---|---|---|
| Repository and local development | Python package, Dockerfile, Docker Compose API/PostgreSQL, environment example, migration and development guides | Local backend development path present; no production deployment |
| API | FastAPI health/readiness, request IDs/error envelope, authenticated `/api/v1/me`, `/api/v1/chat`, owner-scoped memory create/list/read/forget, action validation | Main memory/chat API path implemented; authentication needs configured external OIDC, and chat/model/database live integration remains unverified |
| Authentication and identity | RS256 OIDC validation against configured issuer, audience, and JWKS; verified subject scopes memory and chat | Implemented and tested; fails closed with 503 when unconfigured/provider unavailable and 401 for missing/invalid bearer credentials |
| Model layer | Provider-neutral client, mock client, Nebius Token Factory adapter, bounded structured response parsing | Wired to chat when `NEBIUS_API_KEY` is configured; live endpoint, credentials, quota, and model behavior are not demonstrated |
| Agent orchestration | Intent router, bounded planner, and structured response invocation used by chat application service | Chat structured generation is integrated; full router-to-policy-to-execution lifecycle is not integrated into chat |
| Memory domain and persistence | Schemas, SQLAlchemy model/repository/service, owner-scoped API routes, request-scoped sessions and transaction handling | PostgreSQL/pgvector migration and persistence path implemented; no live database migration/API run verified |
| Memory retrieval | BGE-small 384-dimensional provider, vector persistence/search code, bounded ranking, provenance formatter and offline evaluation | Retrieval is connected to chat and memory creation; live model/vector quality and PostgreSQL retrieval performance remain unverified |
| Security policy | Server-defined tool policy, target allowlists, principal grants, canonical action hash, approval evidence checks | Action validation fails closed; durable grants/approvals and policy-authorized execution remain missing |
| Tool execution | `ToolRunner` checks policy before dispatch | Boundary exists; no production executors/connectors, outcome verification, or integrated audit trail |
| Database and migrations | PostgreSQL/pgvector Compose service, async SQLAlchemy engine/session, Alembic `0001` migration with vector extension, table and indexes | Schema and wiring implemented; readiness checks connectivity, not migration status; live migration not verified |
| Durable jobs and scheduler | Directory contracts and architecture plan | Not implemented |
| Guardian | Directory contracts and architecture plan | Not implemented |
| Dashboard | React/Vite workbench; live health, identity, chat, policy-validation, and memory integration; explicit demo mode | Implemented for currently registered APIs; no browser sign-in, and GitHub/Calendar/Notes/Jobs/Guardian remain unavailable because backend routes are absent |
| Telegram | Directory contracts and design rules | Not implemented |
| Nebius hosting | Deployment notes only | Not implemented or demonstrated |
| Tests and CI | Backend unit, integration, and security tests; GitHub Actions CI for Python 3.12/3.13 | CI validates Compose and runs Ruff, formatting, and pytest for Python; dashboard typecheck/tests/build are not in CI; no live infrastructure/provider validation |

## What has been implemented

### 1. Development and API foundation

- `pyproject.toml` defines the installable Python package and runtime/development dependencies.
- `Dockerfile` builds a non-root FastAPI container.
- `compose.yaml` starts PostgreSQL 16 with pgvector and the API. `deploy/compose/init/01-enable-vector.sql` enables the vector extension when a new database volume is initialized.
- `.env.example` and `.gitignore` provide local configuration and secret-handling conventions.
- `src/cortexstone/api/main.py` builds the FastAPI app, generates request IDs, mounts operational and versioned routes, and formats errors into a shared response envelope.
- `src/cortexstone/api/v1/router.py` exposes liveness/readiness and versioned health endpoints, `/api/v1/me`, and action proposal validation.
- `src/cortexstone/api/v1/memories.py` exposes the contract-limited owner-scoped create/list/read/forget routes. `src/cortexstone/api/v1/chat.py` exposes authenticated chat.
- `/ready` checks connectivity to PostgreSQL. It does not verify migration state or model-provider availability.
- `docs/DEVELOPMENT.md` describes local startup and API conventions.

### 2. Dashboard integration

- `frontend/dashboard/` contains the React 18/TypeScript/Vite application. Live API mode is the default; simulated responses require explicit demo mode.
- The API client calls the implemented health, readiness, current-user, chat, action-validation, and owner-scoped memory routes. Memory page envelopes and field names are mapped to the dashboard's view model.
- Protected requests can send an OIDC bearer token entered in Settings. The token stays in page memory for the current tab; OIDC sign-in/token issuance is not implemented.
- Live failures are surfaced without falling back to fixtures. GitHub, Calendar, Notes, Jobs, and Guardian are reported unavailable because their backend routes are not registered.
- This is an API-connected UI, not evidence of a live deployment: no browser-to-live-service acceptance run is recorded here.

### 3. Model clients and structured agent proposals

- `src/cortexstone/agent/models/interface.py` defines provider-neutral message, response, role, and error contracts.
- `mock.py` supports offline development; `nebius.py` calls Nebius Token Factory and handles timeouts, authentication, rate limits, response parsing, and Pydantic validation.
- Router/reasoner prompts and typed route/action/plan schemas are present. Extra fields in action proposals are forbidden so the model cannot add its own authorization or risk claims.
- `IntentRouter` classifies requests and uses a conservative routing decision if inference fails.
- `AgentOrchestrator` provides bounded structured generation and typed action proposals. The chat application invokes this structured-generation entry point; it does not yet run a complete intent-router → policy → executor cycle.
- Chat uses the configured Nebius client only when `NEBIUS_API_KEY` is set. The application does not silently substitute a mock model.

### 4. Memory subsystem foundation

- Memory schemas represent facts, episodes, and skills, including provenance, confidence, sensitivity, timestamps, and inferred status.
- `MemoryItemCreate` now rejects unexpected fields and does not accept an `approved` field; newly created content cannot self-approve a skill through this schema.
- SQLAlchemy provides a memory model with generated UUID defaults, constraints, timestamps, owner/kind/time indexes, and a 384-dimensional pgvector embedding.
- The repository scopes queries and mutations by owner, excludes soft-deleted records by default, supports filters and pagination, and offers soft/hard deletion operations.
- `MemoryService` coordinates lifecycle operations, generates document embeddings on create/update when configured, performs owner-scoped retrieval, and supports content-free forget receipts and bounded export.
- The Alembic `0001` revision enables pgvector and creates `memory_items` with its constraints, indexes, and HNSW vector index. Async engine/session wiring and request-scoped repository/service construction connect the API to this schema.
- The existing BGE-small provider produces normalized 384-dimensional vectors. Retrieval includes vector validation, semantic/recency/confidence ranking, result limits, and a deterministic offline evaluation harness.
- The prompt formatter now escapes and bounds untrusted memory titles and content, preserving the outer context tags and limiting output length.
- `application/chat/ChatService` retrieves no more than five memories for the authenticated principal and filters out deleted, cross-owner, sensitive/internal, and unapproved skill records before model invocation. Recall prompting asks for source/timestamp citations, uncertainty for inferred records, and no unsupported personal claims. Output is validated into `ChatResult`; action proposals remain unexecuted.

The memory feature is wired end to end in code but has not yet been verified against a running PostgreSQL database or a live embedding model. Automated tests demonstrate the service/repository/API contracts, not production operational readiness or retrieval quality.

### 5. Security policy and execution boundary

- `src/cortexstone/security/policy/engine.py` derives risk from server-side tool definitions, checks exact allowlisted targets and permission grants, validates argument names and JSON compatibility, hashes canonical action data, and verifies matching, unexpired approval evidence.
- The API's `/api/v1/actions/validate` endpoint returns a policy result without executing the action.
- `OIDCAuthenticator` validates RS256 bearer tokens against configured issuer, audience, and JWKS values. The verified subject is converted to a `PolicyPrincipal` and is the sole owner identifier used for memory/chat operations.
- Protected routes return 503 when authentication is unavailable or unconfigured, and 401 for missing/invalid bearer credentials. No demo identity fallback is provided.
- `ToolRunner` re-evaluates policy immediately before dispatch and only calls a registered executor after an `ALLOW` result.
- The policy engine and runner have focused unit/security tests.

The security flow remains incomplete for the PRD: token verification relies on an externally configured OIDC issuer; there is no durable permission store/revocation path, persistent approval service/UI, registered production tools, integrated action audit trail, or result-verification service. The notes search policy can be configured, but no Notes connector executor is registered.

### 6. Tests and CI

Backend tests cover health behavior, OIDC token validation and fail-closed routes, memory API ownership and contract behavior, the SQLAlchemy repository/service, BGE provider, memory retrieval/context formatting, chat context filtering and typed response handling, model parsing/routing, policy outcomes, and the tool runner. `.github/workflows/ci.yml` validates Compose configuration and runs Ruff linting, Ruff formatting checks, and pytest across Python 3.12 and 3.13. The dashboard defines typecheck, test, and build scripts, but CI does not invoke them. No fresh dashboard check result or live-service acceptance result is recorded in this review.

The test suite is not a substitute for runtime evidence with a real PostgreSQL schema, live OIDC provider, live model provider, or connector.

## Current repository structure

```text
apps/                         API/worker/scheduler areas; worker and scheduler remain placeholders
deploy/                       Docker and Nebius notes; local Compose setup is at repository root
docs/                         Development guide, architecture, threat-model, runbook placeholders
Documentations/               PRD, HLD/LLD, agent/design rules, integration specs and team tasks
frontend/dashboard/            React/Vite dashboard; live API client for registered backend routes, explicit demo mode
src/cortexstone/
  agent/                      Model interfaces/adapters, prompts, schemas, routing, orchestrator
  api/                        FastAPI app, settings, dependencies, authenticated v1 routes
  application/chat/            Chat use case, bounded context, validated result contracts
  application/memory/          Memory lifecycle service
  db/                         SQLAlchemy base/session/model and Alembic migrations
  memory/                      Schemas, BGE provider, repository, retrieval, evaluation
  security/policy/             Deterministic tool policy engine and compatibility exports
  security/audit/              Audit event contract and in-memory logger
  tools/runner/                Policy-checked execution boundary; no real executors registered
  guardian/, interfaces/, workflows/, connectors/  Future areas; no production connectors/jobs
tests/                         Unit/security tests, retrieval integration test and fixtures
```

## Alignment with the PRD and HLD

### Where the implementation follows the plan

- **Modular monolith:** code is organized into separable modules under one Python package.
- **Model/backend trust boundary:** models return typed proposals; the policy engine separately determines authorization.
- **Least privilege and fail-closed behavior:** policy uses server-owned tool definitions, exact target allowlists, grants, and approval evidence. Protected API routes require configured OIDC and never assume an identity when authentication is unavailable.
- **Source-aware memory design:** provenance and confidence are represented in schemas and included in formatted retrieval context.
- **Bounded recall context:** chat filters owner-scoped memories by status and sensitivity, caps the result set/context size, escapes untrusted memory text, and requires citations and uncertainty markers for recall.
- **Bounded model work:** route/action schemas and orchestrator contain explicit limits.
- **Adapter direction:** model providers and embedding providers have replaceable interfaces.
- **Developer workflow:** Compose and CI provide an initial local development path.

### Where delivery is behind the MVP plan

The implementation now covers a backend vertical slice of **Remember**, authenticated chat, a connected dashboard for registered APIs, and parts of **Protect**. Most of **Act** and the always-on user experience remain plans. There is no accepted end-to-end demonstration using live PostgreSQL/OIDC/model infrastructure, an always-on scheduled brief, or an authorized action executed through a registered connector and verified in audit history.

Specifically, these P0 PRD requirements remain unproven or unimplemented:

- M1–M4: production acceptance of persisted cross-session memory, semantic/temporal retrieval quality, provenance flow from real sources, and forget behavior verified against a live database.
- A1–A7: Telegram morning brief, durable scheduler/worker, durable job state, retries/idempotency, approval workflow, and user-visible statuses.
- G1: connected-repository secret scanning with redaction.
- T1–T8: persisted grants and approvals, sandbox boundary, integrated audit trail, prompt-injection handling across all orchestration paths, revocation, and verified connector outcomes. OIDC token authentication is implemented, but the external provider's live setup is not validated.
- Nebius deployment using an eligible NVIDIA model.
- Dashboard typecheck, frontend tests, and production build added to CI, followed by browser acceptance against the deployed API.

Some planned deliverables are explicitly staged or blocked on decisions (especially model and embedding selection), which is reasonable for a foundation branch. The project should not describe the MVP as complete until those gates are resolved and acceptance evidence exists.

## Main gaps and recommended next work

### P0 — Validate and harden the implemented backend slice

1. Run Alembic against a real PostgreSQL/pgvector database, verify the migration and downgrade strategy, then exercise authenticated memory create/list/read/forget and chat retrieval end to end.
2. Configure live OIDC and Nebius credentials in a controlled environment; validate provider availability, model IDs, quotas, structured response behavior, and operational error reporting.
3. Verify BGE retrieval behavior and quality using representative user data, confirm owner/sensitivity/deletion filters at the database boundary, and document model download/cache behavior.
4. Decide whether conversational history should remain correlation-ID-only or be persisted and owner-scoped; current API does not load/store previous turns.
5. Add database-backed grants/approvals and revocation; keep action proposals non-executable until authorization is durable and tested.
6. Add at least one allowlisted connector end to end through `ToolRunner`, with independent outcome verification and redacted audit records.
7. Implement secret redaction before memory/model/log persistence and validate it with seeded secrets.

### P0 — Then build the always-on path

8. Implement durable jobs, scheduler and worker with leases, checkpoints, bounded retries, idempotency/deduplication, and honest terminal statuses.
9. Implement the Telegram morning brief and test delivery while the developer machine is offline.
10. Deploy on Nebius and verify the exact Token Factory model IDs, quotas, tool/structured-output behavior, worker lifetime, database persistence, secrets, and health checks.

### Documentation and repository hygiene

- Keep the root README and this review synchronized with merged implementation changes and distinguish API wiring from live runtime acceptance.
- Keep superseded sections of `Documentations/MEMORY_API_INTEGRATION_SPEC.md` clearly labeled as historical; its later sections already identify the current contract and defer public search/edit/export.
- Remove already tracked Python bytecode (`*.pyc` under `__pycache__`) from Git and keep it excluded. `.gitignore` does not automatically untrack files already committed.
- Add live migration and PostgreSQL integration evidence before treating the persistence path as operationally validated.

## Overall assessment

**Architecture alignment: good.** The code largely respects the modular-monolith direction and the critical rule that the backend—not the model—decides whether an action may run.

**Current stage: integrated backend vertical slice plus an API-connected dashboard; MVP remains partial.** Authenticated memory create/list/read/forget, PostgreSQL/pgvector migration wiring, BGE embedding persistence/retrieval, bounded chat, policy validation, and the dashboard client for registered API routes are implemented. The highest-value next step is live integration validation against PostgreSQL, OIDC, and the model provider, followed by durable authorization/approval and one verified connector action. Jobs, Telegram, Guardian scanning, production connector routes, and deployment remain future work.

**Review validation:** repository and documentation inspection at PR #22. CI is configured for backend checks; this documentation update did not run tests, frontend checks, or a deployment rehearsal. No live PostgreSQL, OIDC provider, model endpoint, connector, or deployment was exercised.
