# Architecture records

## Current implementation

Cortexstone is implemented as a modular monolith:

- `src/cortexstone/api/` — FastAPI composition, authentication, and versioned routes
- `src/cortexstone/application/` — chat and memory use cases
- `src/cortexstone/agent/` — model interfaces, routing, orchestration, prompts, and typed schemas
- `src/cortexstone/memory/` — memory schemas, embeddings, repositories, ranking, and retrieval
- `src/cortexstone/db/` — SQLAlchemy session/model infrastructure and Alembic migrations
- `src/cortexstone/security/policy/` — deterministic authorization decisions
- `src/cortexstone/security/permissions/` — uncached database grant lookup and audited administration
- `src/cortexstone/security/action_runs/` — durable action lifecycle and redacted execution audit
- `src/cortexstone/tools/runner/` — policy-checked execution boundary
- `frontend/dashboard/` — live/mock React workbench

## Model providers

- Groq is the router provider for low-latency intent and complexity classification.
- Google AI Studio is the reasoner provider for structured chat, planning, and action proposals.
- The routing result sends simple direct chat to Groq; memory-recall, action, complex, and uncertain requests use Google for the response.
- A Groq API key alone enables simple chat. Reasoner requests fail explicitly if `GOOGLE_API_KEY` is not configured.
- Both providers use the shared OpenAI-compatible chat-completions contract.
- API keys are configured independently: `GROQ_API_KEY` and `GOOGLE_API_KEY`.

## Control boundary

The model may propose structured actions, but the model is not an authorization mechanism.

`model output -> typed schema -> current grant lookup -> PolicyEngine -> approval -> ToolRunner -> registered executor -> verification`

Permission grant/revocation routes are administrator-only and constrained by registered server policies. Grant changes and content-free audit events are written atomically; active grants are reloaded on each authorization check, so no cache invalidation is required. The API exposes action validation, but no production executor is registered and validation does not execute an action.

## Persistence

PostgreSQL is the persistence boundary for memory, permissions, approvals, and action runs. pgvector stores 384-dimensional BGE embeddings. Alembic migrations `0001`–`0004` create memory/vector storage, permission and audit tables, approvals, and durable action-run lifecycle state. Permission/approval changes and their audit records share a transaction. Every `ToolRunner` requires an `ActionRunRecorder`, and attempt/state changes are committed atomically with redacted lifecycle audit events.

## Deferred architecture

- Identity-provider role synchronization
- Conversation history persistence
- Worker and scheduler processes
- Connector registry and provider executors
- Action outcome verification and recovery for interrupted runs
- Guardian finding storage
- Independent action outcome verification
- Production deployment topology and backups

Record material decisions here using context, alternatives, consequences, and migration implications. Approved architecture changes must remain consistent with the central HLD/LLD.
