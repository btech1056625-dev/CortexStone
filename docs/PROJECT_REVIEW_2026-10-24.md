# Cortexstone Project Review

**Review date:** 24 October 2026  
**Reviewed revision:** `0e79e35` (`main`, aligned with `origin/main`)  
**Review scope:** Current repository implementation compared with `Documentations/Cortexstone_PRD.md`, `Documentations/Cortexstone_Architecture_HLD_LLD.md`, the agent and design rules, and the current integration specifications.

## Executive summary

Cortexstone has moved beyond the original documentation-only scaffold. The repository now contains a working foundation for the FastAPI service, local PostgreSQL/pgvector development, model adapters and routing, a bounded agent proposal flow, a reusable memory subsystem, and deterministic server-side action policy. A substantial unit/security test suite and a CI workflow are also present.

The implementation follows the **intended architecture direction** well: a modular monolith, replaceable model adapters, typed action proposals, fail-closed authorization, explicit owner-scoped memory operations, and separation between policy decisions and tool execution. The current code is still an **early foundation, not the MVP described in the PRD**. The major user journeys are not connected end to end, and several required systems do not exist yet.

In particular, the repository does not yet provide authenticated chat or memory API routes, a deployed PostgreSQL memory schema/migration, a production embedding provider, registered connector executors, durable jobs, Telegram, Guardian scanning, a dashboard, or a Nebius deployment. The current policy endpoint fails closed until a trusted identity provider is supplied. No tests were run as part of this review; CI is configured to run lint, formatting, and pytest on Python 3.12 and 3.13.

## Implementation status at a glance

| Area | Current state | Assessment against plan |
|---|---|---|
| Repository and local development | Python package, Dockerfile, Docker Compose API/PostgreSQL, vector extension initialization, environment example, development guide | Foundation present; no production deployment |
| API | FastAPI app, health/readiness checks, request IDs, shared error envelope, `/api/v1/actions/validate` | Partial; no chat or memory routes and authentication is not implemented |
| Model layer | Provider-neutral client contract, mock client, Nebius Token Factory client, router/reasoner roles, structured-output parsing | Useful foundation; actual deployment model availability/quotas are not demonstrated, and API composition does not yet wire the model into chat |
| Agent orchestration | Intent router plus bounded planner returning typed `ProposedAction` objects | Partial; not integrated into the API, policy, memory, or execution lifecycle; does not yet deliver a complete chat answer/task flow |
| Memory domain and lifecycle | Pydantic schemas, SQLAlchemy memory model, owner-scoped repository, service methods for create/list/get/update/forget/export | Substantial domain layer; no memory HTTP routes or production persistence startup/migrations |
| Memory retrieval | Ranking, provenance formatter, embedding interface/configuration, offline lexical benchmark and 20-question fixture | Evaluation foundation only; no concrete production embedder or persisted vector search, and stored records are not currently assigned embeddings on create |
| Security policy | Server-defined tool policy, target allowlists, principal grants, canonical action hash, approval evidence checks, fail-closed API identity dependency | Strong foundation; durable permission/approval services and real authentication are missing |
| Tool execution | `ToolRunner` checks policy immediately before calling a registered executor | Boundary exists; no production executors/connectors are registered, and result verification/audit are not integrated |
| Database and migrations | PostgreSQL/pgvector Compose service, SQLAlchemy base/session/model code, UUID defaults | Database service exists; no Alembic configuration or schema migration creates the application tables; memory embedding column is still `Text` |
| Durable jobs and scheduler | Directory contracts and architecture plan | Not implemented |
| Guardian | Directory contracts and architecture plan | Not implemented |
| Telegram and dashboard | Directory contracts and design rules | Not implemented |
| Nebius hosting | Deployment notes only | Not implemented or demonstrated |
| Tests and CI | Unit, integration, and security tests; GitHub Actions CI for Python 3.12/3.13 | Good planned coverage and automation; review did not execute tests or confirm a CI run result |

## What has been implemented

### 1. Development and API foundation

- `pyproject.toml` defines the installable Python package and runtime/development dependencies.
- `Dockerfile` builds a non-root FastAPI container.
- `compose.yaml` starts PostgreSQL 16 with pgvector and the API. `deploy/compose/init/01-enable-vector.sql` enables the vector extension when a new database volume is initialized.
- `.env.example` and `.gitignore` provide local configuration and secret-handling conventions.
- `src/cortexstone/api/main.py` builds the FastAPI app, generates request IDs, mounts operational and versioned routes, and formats errors into a shared response envelope.
- `src/cortexstone/api/v1/router.py` exposes liveness/readiness and versioned health endpoints, plus action proposal validation.
- `/health/ready` checks connectivity to PostgreSQL. The current health check does not mean application tables or migrations exist.
- `docs/DEVELOPMENT.md` describes local startup and API conventions.

### 2. Model clients and structured agent proposals

- `src/cortexstone/agent/models/interface.py` defines provider-neutral message, response, role, and error contracts.
- `mock.py` supports offline development; `nebius.py` calls Nebius Token Factory and handles timeouts, authentication, rate limits, response parsing, and Pydantic validation.
- Router/reasoner prompts and typed route/action/plan schemas are present. Extra fields in action proposals are forbidden so the model cannot add its own authorization or risk claims.
- `IntentRouter` classifies requests and falls back to a conservative routing decision if inference fails.
- `AgentOrchestrator` has hard-coded iteration, proposal-count, and timeout limits and returns typed proposals. This is not yet a complete conversational workflow: it is not wired into a chat route, does not perform the policy/execution cycle, and does not provide memory recall responses.

### 3. Memory subsystem foundation

- Memory schemas represent facts, episodes, and skills, including provenance, confidence, sensitivity, timestamps, and inferred status.
- `MemoryItemCreate` now rejects unexpected fields and does not accept an `approved` field; newly created content cannot self-approve a skill through this schema.
- SQLAlchemy provides a memory model with generated UUID defaults, constraints, timestamps, and owner/kind/time indexes.
- The repository scopes queries and mutations by owner, excludes soft-deleted records by default, supports filters and pagination, and offers soft/hard deletion operations.
- `MemoryService` coordinates lifecycle operations, content-free forget receipts, optional audit events, and bounded export.
- Retrieval includes vector validation, semantic/recency/confidence ranking, result limits, and a deterministic offline evaluation harness. A 20-question fixture provides evaluation cases for recall, provenance, deleted records, and owner isolation.
- The prompt formatter now escapes and bounds untrusted memory titles and content, preserving the outer context tags and limiting output length.

This is not yet a deployable memory feature. There is no migration creating `memory_items`, the embedding column is a `Text` placeholder, the production embedding provider has not been implemented/selected, and the repository's create path does not generate/store document embeddings. The offline benchmark seeds synthetic embeddings directly, so its results do not establish production semantic retrieval quality.

### 4. Security policy and execution boundary

- `src/cortexstone/security/policy/engine.py` derives risk from server-side tool definitions, checks exact allowlisted targets and permission grants, validates argument names and JSON compatibility, hashes canonical action data, and verifies matching, unexpired approval evidence.
- The API's `/api/v1/actions/validate` endpoint returns a policy result without executing the action.
- `get_policy_principal()` currently returns HTTP 503 because authentication is not configured. This is deliberately fail-closed, but it means the endpoint is not available for normal authenticated use yet.
- `ToolRunner` re-evaluates policy immediately before dispatch and only calls a registered executor after an `ALLOW` result.
- The policy engine and runner have focused unit/security tests.

The security flow remains incomplete for the PRD: there is no real login/identity integration, durable permission store/revocation path, persistent approval service/UI, registered production tools, action audit integration, or result-verification service. The notes search policy can be configured, but no Notes connector executor is registered.

### 5. Tests and CI

Tests now cover health behavior, model parsing and routing, action schema validation, orchestrator limits, memory models/repositories/services/ranking/formatting/evaluation, the retrieval-to-prompt boundary, policy outcomes, and the tool runner. `.github/workflows/ci.yml` runs Ruff linting, Ruff formatting checks, and pytest across Python 3.12 and 3.13.

The test layout is stronger than the original scaffold, but the test suite is not a substitute for integration evidence with a real PostgreSQL schema, real model provider, authentication, or live connector. This review did not execute the tests, so no pass/fail claim is made here.

## Current repository structure

```text
apps/                         API/worker/scheduler areas; worker and scheduler remain placeholders
deploy/                       Docker and Nebius notes; local Compose setup is at repository root
docs/                         Development guide, architecture, threat-model, runbook placeholders
Documentations/               PRD, HLD/LLD, agent/design rules, integration specs and team tasks
frontend/dashboard/            Placeholder; no dashboard application is present
src/cortexstone/
  agent/                      Model interfaces/adapters, prompts, schemas, routing, orchestrator
  api/                        FastAPI app, settings, dependencies, v1 routes and schemas
  application/memory/          Memory lifecycle service
  db/                         SQLAlchemy base, async session, memory model; migration placeholder
  memory/                      Schemas, embedding abstraction, repository, retrieval, evaluation
  security/policy/             Deterministic tool policy engine and compatibility exports
  security/audit/              Audit event contract and in-memory logger
  tools/runner/                Policy-checked execution boundary; no real executors registered
  guardian/, interfaces/, workflows/, connectors/  README-only future areas
tests/                         Unit/security tests, retrieval integration test and fixtures
```

## Alignment with the PRD and HLD

### Where the implementation follows the plan

- **Modular monolith:** code is organized into separable modules under one Python package.
- **Model/backend trust boundary:** models return typed proposals; the policy engine separately determines authorization.
- **Least privilege and fail-closed behavior:** policy uses server-owned tool definitions, exact target allowlists, grants, and approval evidence. The API returns unavailable when it cannot establish trusted identity.
- **Source-aware memory design:** provenance and confidence are represented in schemas and included in formatted retrieval context.
- **Bounded model work:** route/action schemas and orchestrator contain explicit limits.
- **Adapter direction:** model providers and embedding providers have replaceable interfaces.
- **Developer workflow:** Compose and CI provide an initial local development path.

### Where delivery is behind the MVP plan

The implementation currently covers pieces of **Remember** and **Protect**, while most of **Act** and the user-facing experience are still plans. There is no connected end-to-end demonstration of cross-session memory through the API, an always-on scheduled brief, or an authorized action executed through a registered connector and verified in audit history.

Specifically, these P0 PRD requirements remain unproven or unimplemented:

- M1–M4: persisted cross-session memory, actual semantic/temporal retrieval, production provenance flow, and complete forget behavior with persistence.
- A1–A7: Telegram morning brief, durable scheduler/worker, durable job state, retries/idempotency, approval workflow, and user-visible statuses.
- G1: connected-repository secret scanning with redaction.
- T1–T8: end-to-end authentication/authorization, persisted grants and approvals, sandbox boundary, audit trail, prompt-injection handling throughout orchestration, revocation, and verified connector outcomes.
- Nebius deployment using an eligible NVIDIA model.

Some planned deliverables are explicitly staged or blocked on decisions (especially model and embedding selection), which is reasonable for a foundation branch. The project should not describe the MVP as complete until those gates are resolved and acceptance evidence exists.

## Main gaps and recommended next work

### P0 — Connect the main trust and memory loop

1. Select and document the production embedding model and dimension; implement a concrete provider and generate/store embeddings on memory creation/update.
2. Add reviewed Alembic migrations for the memory table and required indexes, using pgvector instead of a text placeholder once the vector dimension is set.
3. Wire SQLAlchemy session creation, memory repository/service, and authenticated owner identity into FastAPI. Implement the documented create/list/get/search/update/forget routes and commit transactions deliberately.
4. Wire chat → router → orchestrator → memory context/model response; keep retrieved content treated as untrusted all the way through prompt construction.
5. Complete authentication before exposing user data or accepting a real policy principal. Preserve the current fail-closed behavior until then.
6. Persist permission grants, revocation, approval decisions, and action/audit records. Add exact action-bound approval UX before any external write.
7. Add at least one allowlisted connector end to end through `ToolRunner`, with independent outcome verification and redacted audit records.
8. Implement secret redaction before memory/model/log persistence and validate it with seeded secrets.

### P0 — Then build the always-on path

9. Implement durable jobs, scheduler and worker with leases, checkpoints, bounded retries, idempotency/deduplication, and honest terminal statuses.
10. Implement the Telegram morning brief and test delivery while the developer machine is offline.
11. Deploy on Nebius and verify the exact Token Factory model IDs, quotas, tool/structured-output behavior, worker lifetime, database persistence, secrets, and health checks.

### Documentation and repository hygiene

- Update the root `README.md` implementation-status paragraph. It still describes only the minimal API bootstrap and says product workflows are not implemented, while memory/policy/orchestrator code now exists.
- Reconcile `Documentations/MEMORY_API_INTEGRATION_SPEC.md` with the current implementation. It still includes the old `approved` creation field/example and describes memory prompt content as unescaped, both of which are stale relative to the current code.
- Remove already tracked Python bytecode (`*.pyc` under `__pycache__`) from Git and keep it excluded. `.gitignore` does not automatically untrack files already committed.
- Add real migration and PostgreSQL integration evidence before treating the SQLAlchemy model as an operational database schema.

## Overall assessment

**Architecture alignment: good.** The code largely respects the modular-monolith direction and the critical rule that the backend—not the model—decides whether an action may run.

**MVP completeness: early / partial.** The repository contains useful foundations and testable modules, but the key product paths are not yet wired together or deployed. Focus next on closing a single vertical slice—authenticated memory save/retrieve/forget backed by a real migration and embedding provider—then complete one policy-gated connector action with durable approval, audit, and verification before expanding into jobs, Telegram, Guardian, and UI.

**Review validation:** static inspection of the current `main` tree and documentation. CI workflow is present; no local tests, lint, deployment, or live provider checks were run for this report.
