# Cortexstone

Cortexstone is a private assistant built around three product pillars: **Remember, Act, Protect**. The repository follows a modular-monolith design with explicit module contracts. The API is implemented; worker and scheduler entry points remain planned.

## Repository map

```text
apps/                 API application plus worker and scheduler placeholders
src/cortexstone/      Product package: API, application, domain, adapters, and infrastructure
frontend/dashboard/   React/Vite dashboard with live API mode and explicit demo mode
tests/                Unit, integration, security, reliability, and shared fixtures
deploy/               Local composition, container, and Nebius deployment assets
docs/                 Architecture notes, threat model, and operational runbooks
Documentations/       Product requirements, system design, and team rules
```

README files in scaffolded modules describe intended responsibilities; the implementation status below identifies which components are present and which remain planned.

## Architecture guardrails

- The model proposes; deterministic backend policy authorizes; the restricted runner executes; verification establishes the result.
- Keep provider, agent runtime, sandbox, and connector integrations behind replaceable adapters.
- Persist jobs, approvals, and product state. Keep retries bounded and side effects idempotent or independently verified.
- Default connector access to read-only. Revalidate permission and action-bound approval immediately before execution.
- Keep raw secrets out of model context, logs, audit events, notifications, and persisted Guardian evidence.
- Report success only after a tool result or independent verification.
- Do not split modules into services without a deliberate architecture decision supported by operational needs.

## Source documents

- [Product Requirements Document](./Documentations/Cortexstone_PRD.md)
- [System Architecture, HLD & LLD](./Documentations/Cortexstone_Architecture_HLD_LLD.md)
- [Agent Rules](./Documentations/AGENT_RULES.md)
- [Design Rules](./Documentations/DESIGN_RULES.md)

## Implementation status

The repository includes a FastAPI backend with PostgreSQL/pgvector Compose startup and Alembic migrations, OIDC bearer-token verification, owner-scoped memory endpoints, authenticated chat through the agent/model adapter, and policy-only action validation. The React/Vite dashboard defaults to live mode and connects to the health, identity, chat, action-validation, and memory APIs; simulated data requires explicitly switching to demo mode. Dashboard Settings accepts an OIDC access token in page memory. Login and token issuance still depend on an external OIDC provider and are not implemented here. GitHub, Calendar, Notes, Jobs, and Guardian are not registered as live backend routes.

CI currently runs Compose configuration validation and Python lint, formatting, and tests on Python 3.12 and 3.13. Dashboard typecheck, tests, and production build are not yet part of CI. The backend vertical slice and dashboard integration have not been accepted through a live PostgreSQL/OIDC/model deployment rehearsal; the MVP remains in progress.

See [development setup and API integration conventions](./docs/DEVELOPMENT.md) to start the local environment and run checks.
