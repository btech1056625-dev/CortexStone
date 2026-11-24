# Cortexstone dashboard

React 18 + TypeScript (strict) + Vite. A dark, responsive operational workbench for Cortexstone.

## Run

```bash
cd frontend/dashboard
npm ci
cp .env.example .env     # public configuration only
npm run dev              # http://localhost:5173
```

Checks: `npm run typecheck` · `npm test` · `npm run build` · `npm audit`

## Environment (all `VITE_*` values are bundled into the browser: never put secrets here)

| Variable | Values | Notes |
|---|---|---|
| `VITE_DATA_MODE` | `live` (default) or `mock` | Live is the default. Mock data is available only when explicitly selected. Anything else shows a configuration error and makes no requests. |
| `VITE_API_BASE_URL` | empty, or an `https` origin | Empty uses the Vite dev proxy. `http` is accepted only for localhost. Credentials, query strings and fragments are rejected. |
| `VITE_API_PROXY_TARGET` | URL, default `http://localhost:8000` | Dev proxy target only; read by `vite.config.ts`, not bundled. |

For cross-origin hosting, configure the API's `CORTEXSTONE_CORS_ORIGINS` with the dashboard's exact origin. This is a backend setting in the repository-root `.env`, not a `VITE_*` value. The Vite development proxy avoids cross-origin requests locally.

## Modes

- **live**: default mode; uses the real health, readiness, identity, chat, policy-validation, and owner-scoped memory routes. Unreachable API, 401/403, 503 and unsupported routes are surfaced without fallback.
- **mock**: simulated responses only when explicitly selected. The shared header labels this mode as a sandbox.

## Backend

```bash
docker compose up --build --wait   # repo root; API on :8000
curl localhost:8000/health
```

Protected API routes accept either a configured OIDC bearer token or a short-lived session issued after Google/GitHub OAuth sign-in. OAuth sessions and provider credentials remain in page memory/server-side encrypted storage respectively; reloading the tab clears the session. Set `VITE_OAUTH_API_ORIGIN` only when the API callback origin differs from `VITE_API_BASE_URL` (for example with the local Vite proxy).

## What is real

| Section | Live mode | Mock mode |
|---|---|---|
| Health (`/health`, `/ready`, `/api/v1/me`) | Live | Simulated |
| Actions: `POST /api/v1/actions/validate` | Live; policy validation only, never execution | Simulated policy |
| Overview approvals and activity | Not available (no endpoint) | Simulated |
| Chat | Live (`POST /api/v1/chat`) | Simulated |
| Memory (list, create, filter, forget) | Live (`/api/v1/memories`) | Simulated, create/forget persist for the session |
| Google Calendar | Per-user OAuth; primary-calendar event reads and write operations through policy and one-time approval | Simulated data |
| GitHub | OAuth sign-in and GitHub App account connection; issue reads only for configured repositories | Simulated data |
| Cortexstone Notes | Not registered on the backend; shown unavailable and not called | Simulated data |
| Jobs, Guardian | Not available (no routes) | Simulated; Guardian scanning is disabled with an explanation |
| Settings | Connection details | Mode details |

## Security notes

- No secrets or API credentials belong in the frontend. Protected-route identity comes from the verified OIDC bearer token.
- All server and model text is rendered as plain text; the codebase has no `innerHTML`.
- Action arguments are held in memory only. The sole browser-storage use is the sidebar-collapsed preference.
- Destructive actions (forget) use a confirmation dialog and block duplicate submission.
- OAuth callback origins are checked against the exact configured dashboard allowlist. The browser never receives provider client secrets or stored provider tokens.
- Calendar writes require a current policy grant and one-time approval; create operations require an `Idempotency-Key`.
- GitHub App access should be limited to Issues read-only and selected repositories. The API also enforces its exact repository allowlist.
- The API enables CORS only for explicit origins configured in `CORTEXSTONE_CORS_ORIGINS`; wildcards are rejected. Use the Vite dev proxy for local development.
