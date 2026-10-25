# Dashboard source

The React application is organized into routed pages, shared UI and dialog components, and a typed API client. It defaults to live API mode. Backend access is centralized in `api/client.ts`; mock mode is explicit, and live failures are surfaced without falling back to sample data. OIDC access tokens entered in Settings remain in memory for the current tab only.

The current backend registers health, identity, chat, policy validation, and owner-scoped memory routes. GitHub, Calendar, Notes, jobs, and Guardian routes are not registered; live mode reports those views unavailable and makes no requests to them. `POST /api/v1/actions/validate` is policy validation only and never executes a proposal.

The dashboard does not persist the OIDC access token: a token entered in Settings is held in page memory and sent only as a bearer token to protected API routes. Keep provider credentials and connector authorization on the backend. The browser does not persist action payloads or user identity.
