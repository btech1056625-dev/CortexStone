# Engineering documentation

This directory contains implementation records, architecture decisions, threat-model evidence, and operations guidance.

## Documentation status

| Area | Status | Evidence |
|---|---|---|
| Local API foundation | Implemented | FastAPI, Docker Compose, PostgreSQL/pgvector, Alembic, health/readiness routes |
| Migration-aware readiness | Verified locally | `/ready` requires database connectivity and the packaged Alembic migration heads |
| OIDC authentication | Implemented | RS256 bearer verification and fail-closed protected routes |
| Authenticated memory/chat HTTP acceptance | Verified locally | Signed test bearer tokens reach protected routes against disposable PostgreSQL; CRUD, owner isolation, forget, and database-backed chat recall pass; actual IdP token and live model use remain pending |
| Memory vertical slice | Implemented | Owner-scoped CRUD, persistence, BGE embeddings, pgvector retrieval |
| Chat vertical slice | Implemented | Authenticated chat, model adapters, bounded retrieval, typed responses |
| Split model providers | Configured | Groq handles routing; Google AI Studio handles reasoning |
| Policy boundary | Implemented | Server-side allowlists, grants, approval checks, and policy-checked runner |
| Dashboard | Implemented | Live API mode, mock mode, memory/chat/settings UI |
| Dashboard quality checks | Verified locally | 18 tests pass; typecheck and production build pass |
| Docker Compose configuration | Verified locally | `docker compose --env-file .env.example config --quiet` passes |
| Python quality checks | Verified locally | Backend tests, Ruff lint, and formatting pass on Python 3.12 |
| Local PostgreSQL + BGE acceptance | Verified 24 Nov 2026 | Memory lifecycle and BGE retrieval passed; isolated PostgreSQL applied migrations through `0004` and verified permission, approval, action-run lifecycle, and audit persistence |
| Live chat-model APIs | Pending keys | Groq and Google AI Studio variables in local `.env` are placeholders; no live inference call was made |
| Permission grants and revocation | Implemented and locally verified | PostgreSQL-backed exact grants, uncached policy lookup, admin grant/revoke routes, and transactional permission audit events; no IdP role synchronization |
| Durable approvals | Implemented | Migration `0003`, owner-scoped request/decision API, exact-action binding, expiry/revocation, and transactional approval audit; no production write tool/executor is registered |
| Action execution audit | Implemented and locally verified | Migration `0004`, required `ToolRunner` run recorder, durable lifecycle states, and allowlisted redacted lifecycle audit events |
| Production connectors | Initial read-only GitHub workflow implemented; live access unverified | GitHub issue reads are conditionally registered through `ToolRunner` for exact allowlisted repositories; local HTTP tests use a mock provider; no Calendar, Notes, or write executor is registered |
| Jobs and scheduler | Not implemented | Worker and scheduler directories are placeholders |
| Telegram | Not implemented | No Telegram delivery service or route |
| Guardian | Not implemented | No repository scanning or finding persistence |
| Production deployment | Not implemented | No Nebius deployment rehearsal or hosted acceptance record |

## Source of truth

- Product requirements: [Cortexstone_PRD.md](../Documentations/Cortexstone_PRD.md)
- Architecture: [Cortexstone_Architecture_HLD_LLD.md](../Documentations/Cortexstone_Architecture_HLD_LLD.md)
- Agent rules: [AGENT_RULES.md](../Documentations/AGENT_RULES.md)
- Design rules: [DESIGN_RULES.md](../Documentations/DESIGN_RULES.md)
- Implementation review: [PROJECT_REVIEW_2026-10-25.md](./PROJECT_REVIEW_2026-10-25.md)

Do not mark infrastructure or provider features complete based only on interfaces or unit tests. Completion requires a reproducible runtime acceptance record.
