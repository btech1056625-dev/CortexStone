# Audit trail

Permission grants and revocations are recorded in PostgreSQL `security_audit_events` in the same transaction as the permission change. These events contain the verified actor and subject, grant identifier, tool, scope, and exact target set; they never contain action arguments or user content.

The broader audit trail for action attempts, approvals, denials, execution outcomes, failures, retention, and tamper-resistant storage remains unimplemented. Persist only redacted summaries and safe error codes; never include credentials, raw secrets, or forgotten memory content.
