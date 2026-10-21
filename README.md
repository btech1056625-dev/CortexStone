# Cortexstone

Cortexstone is a private assistant built around three product pillars: **Remember, Act, Protect**. This repository is organized as a modular monolith: domain modules share one codebase and explicit contracts, while the API, worker, and scheduler are separate runtime entry points that can be tested and deployed independently.

## Repository map

```text
apps/                 Independently runnable API, worker, and scheduler processes
src/cortexstone/      Product package: API, application, domain, adapters, and infrastructure
frontend/dashboard/   User-facing dashboard; framework choice remains open
tests/                Unit, integration, security, reliability, and shared fixtures
deploy/               Local composition, container, and Nebius deployment assets
docs/                 Architecture notes, threat model, and operational runbooks
Documentations/       Product requirements, system design, and team rules
```

The README files in the scaffolded directories describe their intended responsibilities and the work that belongs there. They are planning notes, not claims that the components are implemented.

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

This repository currently contains product documentation and an implementation-ready directory scaffold. Runtime code, dependency manifests, credentials, and deployment claims must be added and validated separately.
