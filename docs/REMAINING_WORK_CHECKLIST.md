# Cortexstone Remaining Work Checklist

Status reflects repository and local verification as of 24 November 2026. Phase 1 local verification is complete; live IdP/provider and production-data checks are intentionally deferred to final-go acceptance.

## Phase 1 — Validate the Existing Backend

- [x] Add automated ASGI HTTP tests for signed RS256 bearer-token access to memory and chat routes.
- [x] Verify authenticated subject scoping for memory and chat in those tests.
- [x] Verify unauthenticated or unconfigured protected requests fail closed.
- [x] Run authenticated memory HTTP acceptance against an isolated PostgreSQL/pgvector database; verify create, list, read, cross-owner isolation, and forget.
- [x] Run authenticated chat HTTP acceptance against that database and verify owner-scoped memory reaches the chat context using a mock model.
- [x] Verify configured OIDC discovery metadata and JWKS endpoint are reachable and match issuer/JWKS configuration.
- [x] Verify issuer, audience, expiry, signing-key rotation, invalid credentials, and provider-unavailable behavior with automated tests.
- [x] Run the deterministic offline 20-question benchmark: 20/20 recall, citation, inference, and negative-control checks passed.
- [x] Verify owner isolation and forget over authenticated HTTP against PostgreSQL; the API currently accepts user-origin memories only.
- [x] Keep conversation history non-persistent for this MVP; `conversation_id` is an opaque correlation value echoed by the API.
- [x] Test PostgreSQL migration upgrade, downgrade to base, repeat upgrade, and final head (`0002`) on a disposable database.
- [x] Make `/ready` fail when database migrations are missing or not at the packaged Alembic head.
- [x] Keep model-provider readiness feature-scoped: `/ready` checks database/schema; chat returns unavailable when required model credentials/providers are missing.

## Final-Go Acceptance — Intentionally Deferred

These are release-time checks, not blockers for the completed Phase 1 local acceptance. Keep them unchecked until tested against the actual identity provider, configured production providers, and representative data.

- [ ] Use a bearer token issued by the configured OIDC provider to exercise protected memory and chat routes.
- [ ] Run authenticated chat with live OIDC, Groq, and Google AI Studio; verify configured model IDs, quotas, timeouts, and structured responses.
- [ ] Run the 20-question benchmark with production BGE retrieval and representative user/source data; verify the 85% factual-recall target and source accuracy.
- [ ] Verify connector-source provenance through a real ingestion path once production connectors are available.

## Phase 2 — Durable Approvals and Action Safety

- [x] Persist owner-scoped approval requests and approved/rejected/revoked/expired decisions; audit each request and decision transactionally. The API exposes create/list/decide/revoke routes.
- [x] Bind approval evidence to a canonical SHA-256 hash of tool, exact target, purpose, idempotency key, and canonical arguments, plus the principal.
- [x] Reject changed, expired, revoked, rejected, or wrong-principal approval evidence in policy evaluation tests.
- [x] Recheck current permission grants with an uncached lookup during `ToolRunner` pre-dispatch; a test confirms revocation between preflight and dispatch blocks the executor.
- [x] Persist permission grant/revocation audit events atomically with the permission change; these are not action-execution audit records.
- [x] Persist action attempts and lifecycle status (`pending`, `awaiting_approval`, `denied`, `running`, `succeeded`, `failed`, `cancelled`) in PostgreSQL; `ToolRunner` requires the recorder and persists transitions before/after dispatch.
- [x] Persist attempts, accepted approvals, denials, execution outcomes, and failures as redacted audit events. Audit details use allowlisted identifiers and codes only; action arguments, targets, purposes, executor results, and exception messages are not stored in action-run audit records.
- [x] Implement supported-pattern secret redaction before data reaches prompts, memory, logs, or audit records; document detection limitations.
- [x] Expand prompt-injection tests across chat, memory, orchestration, and mocked connector-context paths; production connectors remain pending.
- [x] Document the in-process restricted `ToolRunner` boundary and test default-deny behavior for unregistered code-execution tools; this is not an OS sandbox.
- [x] Verify with unit tests and mock executors that denied actions, missing/expired approvals, and revoked permissions do not dispatch. Production connector behavior is not yet exercised.

## Phase 3 — Production Connectors

- [x] Deliver an authenticated, read-only GitHub issue lookup through `ToolRunner`; local HTTP integration is mock-verified, live GitHub access remains unverified.
- [x] Conditionally register the GitHub issue reader with `ToolRunner` only when a token and exact repository allowlist are configured.
- [x] Use a documented least-privilege GitHub fine-grained token with Issues read-only permission and exact repository scopes.
- [ ] Independently verify external connector outcomes before reporting success; this initial read-only workflow validates returned repository and issue identity but performs no side effect.
- [x] Bound GitHub calls with connection/total timeouts and a response-size cap; the idempotent GET fails without automatic retries.
- [x] Identify that local provider tests use `httpx.MockTransport`; live GitHub credentials and access have not been tested.
- [x] Document GitHub permission scope, environment-based credential handling, and rotation.

## Phase 4 — Durable Jobs, Scheduling, and Telegram

- [ ] Implement durable job state, scheduling, worker leases, and checkpoints.
- [ ] Add bounded retries, duplicate-work protection, and crash recovery.
- [ ] Report queued, awaiting-approval, running, succeeded, failed, and cancelled states accurately.
- [ ] Implement authenticated Telegram webhook handling and safe message delivery.
- [ ] Implement and test the scheduled morning brief.
- [ ] Verify five consecutive deliveries, including while the developer machine is offline.
- [ ] Expose job and execution status in the dashboard.

## Phase 5 — Guardian

- [ ] Implement connected-repository secret scanning.
- [ ] Detect all seeded test secrets and redact evidence before storage or display.
- [ ] Persist findings and their severity, status, and safe evidence.
- [ ] Display findings in the dashboard and provide safe notifications.
- [ ] Verify raw secrets never appear in prompts, logs, audit records, or findings.
- [ ] Consider remediation PR drafts only after P0 reliability and safety gates pass.

## Phase 6 — Deployment and Operations

- [ ] Deploy the API, database, worker, and scheduler to the selected host.
- [ ] Verify production model availability, quota, latency, and structured-output behavior.
- [ ] Verify secrets management and database persistence through service/container restarts.
- [ ] Confirm workers and scheduled jobs remain active when clients are offline.
- [ ] Add health checks, dependency-aware readiness, monitoring, and alerting.
- [ ] Run a documented deployment and recovery rehearsal.
- [ ] Record availability during the acceptance window; target at least 95% over five days.
- [ ] Prepare a reproducible operations guide and recorded demo fallback.

## Phase 7 — CI, Dashboard, and Release Evidence

- [ ] Add dashboard typecheck, tests, and production build to CI.
- [ ] Add browser acceptance against a running API.
- [ ] Complete approval, action-history, and Guardian dashboard flows.
- [ ] Add clear loading, error, retry, and unavailable states.
- [ ] Ensure action UI never reports success before backend verification.
- [ ] Keep project status and integration documentation aligned with verified behavior.
- [ ] Capture acceptance evidence for memory, approvals, connectors, recovery, secrets, and deployment.

## Phase 8 — P1 Features

- [ ] Add memory edit and export, if retained in scope.
- [ ] Complete memory inspector and timeline UX.
- [ ] Add reusable skill generation and persistence.
- [ ] Add dependency and workflow checks.
- [ ] Add approved draft-remediation workflows.

## Phase 9 — P2 Stretch Goals

- [ ] Add weekly security posture reporting after P0 work is stable.
- [ ] Add further integrations only after P0 acceptance.
- [ ] Keep voice out of scope unless explicitly approved.

## MVP Exit Gates

- [ ] Cross-session, source-aware memory recall meets the benchmark.
- [ ] Forget is verified to make deleted memory unretrievable.
- [ ] A scheduled brief is delivered while the user is offline.
- [ ] At least one permission-controlled tool action is executed and independently verified.
- [ ] Guardian detects seeded secrets and redacts all evidence.
- [ ] Jobs and actions have durable status, safe recovery, and traceable audit history.
- [ ] The deployed system passes an end-to-end acceptance rehearsal.
