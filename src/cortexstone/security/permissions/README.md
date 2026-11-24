# Permissions

Permission grants are persisted per principal, registered tool, scope, and exact target set. Repeating an identical active grant is idempotent. The policy engine performs an uncached database lookup on every asynchronous evaluation, including immediately before `ToolRunner` dispatch. Missing grants and permission-store errors fail closed.

Grant and revoke operations are available only to verified OIDC subjects listed in `CORTEXSTONE_PERMISSION_ADMIN_SUBJECTS`. `POST /api/v1/admin/permissions` only accepts the scope and targets declared by a server-owned tool policy. `DELETE /api/v1/admin/permissions/grants/{grant_id}` revokes one grant; `DELETE /api/v1/admin/permissions/principals/{principal_id}` revokes all active grants for offboarding or role changes.

Grant changes and their content-free audit events are committed in the same PostgreSQL transaction. Revocations are retained as history and take effect on the next policy evaluation; no permission cache must be invalidated. An empty administrator allowlist denies all grant administration.

This is an operator-managed grant workflow, not automatic directory/role synchronization. When an organization membership or role changes, an authorized administrator must revoke affected grants and explicitly issue any replacement grants.

For complete offboarding, also disable the identity and revoke its sessions/tokens at the OIDC provider. If the departing subject is in `CORTEXSTONE_PERMISSION_ADMIN_SUBJECTS`, remove it from that configuration and roll out the change; the application-level permission grant table does not control administrator status or revoke already-issued OIDC tokens.
