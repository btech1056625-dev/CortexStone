# Engineering documentation

This directory contains implementation records, architecture decisions, threat-model evidence, and operations guidance.

## Documentation status

| Area | Status | Evidence |
|---|---|---|
| Local API foundation | Implemented | FastAPI, Docker Compose, PostgreSQL/pgvector, Alembic, health/readiness routes |
| OIDC authentication | Implemented | RS256 bearer verification and fail-closed protected routes |
| Memory vertical slice | Implemented | Owner-scoped CRUD, persistence, BGE embeddings, pgvector retrieval |
| Chat vertical slice | Implemented | Authenticated chat, model adapters, bounded retrieval, typed responses |
| Split model providers | Configured | Groq handles routing; Google AI Studio handles reasoning |
| Policy boundary | Implemented | Server-side allowlists, grants, approval checks, and policy-checked runner |
| Dashboard | Implemented | Live API mode, mock mode, memory/chat/settings UI |
| Dashboard quality checks | Verified locally | 18 tests pass; typecheck and production build pass |
| Docker Compose configuration | Verified locally | `docker compose --env-file .env.example config --quiet` passes |
| Python quality checks | Verified locally | 319 backend tests, Ruff lint, and formatting pass on Python 3.12 |
| Local PostgreSQL + BGE acceptance | Verified 24 Nov 2026 | Memory lifecycle and BGE retrieval passed; isolated PostgreSQL applied migrations `0001`–`0002` and verified permission grant, fresh revocation, and audit persistence |
| Live chat-model APIs | Pending keys | Groq and Google AI Studio variables in local `.env` are placeholders; no live inference call was made |
| Permission grants and revocation | Implemented and locally verified | PostgreSQL-backed exact grants, uncached policy lookup, admin grant/revoke routes, and transactional permission audit events; no IdP role synchronization |
| Durable approvals and action audit | Not implemented | Approval workflow and integrated action-attempt/outcome audit remain unbacked |
| Production connectors | Not implemented | `ToolRunner` is present but has no registered production executors |
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
