# Threat model

## Implemented controls

- Protected memory and chat routes require an RS256 OIDC bearer token.
- The verified `sub` claim is the only principal/owner identity for protected operations.
- Authentication is fail-closed if issuer, audience, or JWKS configuration is unavailable.
- Memory queries are scoped to the authenticated owner.
- Memory and chat schemas reject unexpected fields.
- Action schemas forbid model-supplied authorization or risk fields.
- `PolicyEngine` uses server-owned tool definitions and target allowlists.
- Tool permissions are stored per principal, registered tool, read/write scope, and exact target set; missing grants deny.
- Permission grants are read from PostgreSQL without a process cache on every asynchronous policy evaluation, including the runner's pre-dispatch check.
- Grant management requires a verified OIDC subject in `CORTEXSTONE_PERMISSION_ADMIN_SUBJECTS`; grants cannot exceed the server-owned tool policy.
- Grant and revocation changes are committed atomically with metadata-only security audit events. Principal-wide tool-grant revocation supports least-privilege cleanup for offboarding and role changes.
- Approval data must match the canonical action hash and remain unexpired.
- `ToolRunner` revalidates policy immediately before dispatch and requires a durable action-run recorder.
- Action attempts, approval acceptance, denials, outcomes, and failures are atomically recorded with lifecycle audit events. Audit details use allowlisted identifiers and codes; they exclude action arguments, targets, purposes, executor results, and exception messages.
- Memory text is bounded and escaped when formatted into chat context.
- Live dashboard failures are surfaced instead of silently falling back to mock data.

## Protected assets

- User memory content and provenance
- OIDC identities and access tokens
- Model credentials
- Database credentials
- Policy grants and approvals
- Action targets and arguments
- Connector credentials and audit records
- Guardian findings and repository secrets

## Residual risks

- No audit-retention policy. Permission grants and revocations are database-backed, but administrator-managed rather than synchronized automatically from IdP organization roles.
- Revoking tool grants does not invalidate existing OIDC tokens or remove a subject from the configured permission-administrator allowlist; full offboarding must disable the identity at the OIDC provider and update administrator configuration when applicable.
- No production connector executor has been registered.
- Secret redaction is not yet a complete system-wide pipeline; action-run lifecycle audit is redacted, but this does not sanitize prompts, memory, or other application logs.
- Prompt-injection handling has not been proven across every future orchestration and connector path.
- Conversation history is not persisted or bounded as a separate memory product.
- Live PostgreSQL memory lifecycle and BGE retrieval passed a local service-level acceptance run on 24 November 2026.
- Automated ASGI bearer-token HTTP acceptance passed for protected memory and chat routes on 24 November 2026.
- Live Groq/Google inference and hosted deployment are not verified; local model API keys are placeholders.
- OIDC configuration is present locally and automated token-validation tests pass; no live OIDC request was included in the 24 November memory acceptance run.
- The dashboard contains no browser sign-in or token issuance flow.

## Required validation before production

1. Exercise cross-owner, deleted-record, sensitive-record, and unapproved-skill isolation against PostgreSQL.
2. Validate OIDC issuer, audience, JWKS, expiry, and key-rotation behavior.
3. Verify model and embedding providers with live credentials and quotas.
4. Add durable action-run audit retention controls and IdP role synchronization; verify persisted approval expiry and canonical-hash mismatch behavior through the execution path.
5. Seed credentials and injection payloads in all inbound/outbound model and connector paths.
6. Add one connector executor and independently verify its side effect and audit record.
7. Verify deployment secrets, TLS, backups, log redaction, and incident procedures.
