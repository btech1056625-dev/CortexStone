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
| `VITE_DATA_MODE` | `mock` (default) or `live` | Anything else shows a configuration error and makes no requests. |
| `VITE_API_BASE_URL` | empty, or an `https` origin | Empty uses the Vite dev proxy. `http` is accepted only for localhost. Credentials, query strings and fragments are rejected. |
| `VITE_API_PROXY_TARGET` | URL, default `http://localhost:8000` | Dev proxy target only; read by `vite.config.ts`, not bundled. |

## Modes

- **mock**: simulated data for all eight sections, labelled in the shared header as a simulated sandbox. Nothing is described as a real operation.
- **live**: real responses only. Unreachable API, 401/403, 503 and unregistered routes are shown as they are. There is no silent fallback to mock.

## Backend

```bash
docker compose up --build            # repo root; API on :8000
curl localhost:8000/health
```

## What is real

| Section | Live mode | Mock mode |
|---|---|---|
| Health (`/health`, `/ready`, `/api/v1/me`) | Live | Simulated |
| Actions: `POST /api/v1/actions/validate` | Live; policy validation only, never execution | Simulated policy |
| Overview approvals and activity | Not available (no endpoint) | Simulated |
| Chat | Not available (no `/api/v1/chat` route) | Simulated |
| Memory (list, create, filter, forget) | Live (`/api/v1/memories`) | Simulated, create/forget persist for the session |
| GitHub and Google Calendar | Read-only repository, issue, pull-request, workflow-run, and event views | Simulated read-only data |
| Cortexstone Notes | CRUD (`/api/v1/notes`) | Simulated CRUD, session-only |
| Jobs, Guardian | Not available (no routes) | Simulated; Guardian scanning is disabled with an explanation |
| Settings | Connection details | Mode details |

## Security notes

- No secrets, tokens or user identity live in the frontend. The API derives identity server-side.
- All server and model text is rendered as plain text; the codebase has no `innerHTML`.
- Action arguments are held in memory only. The sole browser-storage use is the sidebar-collapsed preference.
- Destructive actions (forget) use a confirmation dialog and block duplicate submission.
- GitHub and Calendar have no write or provider connection controls in this MVP. Notes are the only built-in CRUD connector.
- The backend registers no CORS middleware: use the dev proxy, serve same-origin, or add CORS server-side.
