# Google Calendar connector

The connector operates only on the authenticated user's `primary` calendar and
supports bounded event listing, creation, updates, and deletion. It uses a
per-user Google OAuth credential with the `calendar.events.owned` scope, fixed
Google API hosts, redirects disabled, a 10-second timeout, and a 512 KiB
decompressed response limit. Timed event inputs must include an ISO-8601 offset
and an IANA time zone; list ranges are limited to one year and 100 events.

All operations pass through `ToolRunner`. Reads require a current
`google_calendar.events.read` grant. Create, update, and delete require their
corresponding write grants and one-time approval. Repeated creates use an
idempotency key and deterministic provider event ID. Event text returned by
Google is untrusted content.

## OAuth setup

Configure a Google OAuth client with the callback
`https://<API-host>/api/v1/oauth/google/callback`, then set
`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`CORTEXSTONE_OAUTH_PUBLIC_API_URL`, and an exact
`CORTEXSTONE_OAUTH_DASHBOARD_ORIGINS` allowlist. OAuth also requires an
independent session signing key and Fernet token-encryption key. Generate a
Fernet key with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The dashboard offers Google and GitHub sign-in when their providers are
configured. Google sign-in requests the Calendar scope and connects the
primary calendar directly. A signed-in user can connect or disconnect the other
provider in Integrations. Access and refresh tokens are encrypted in PostgreSQL;
the browser receives only a short-lived Cortexstone session token. Applying
migrations through `0006` is required. OAuth flows use single-use state, PKCE,
and Google OIDC nonce validation.

The API policy still requires exact permission grants. Write approvals are
single-use and expire after 15 minutes. Provider credentials and event contents
are not written to action audit records. Local tests use mocked HTTP transports;
live OAuth consent and Calendar calls require deployment credentials and were
not verified locally.
