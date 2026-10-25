# Dashboard source

The React application is organized into routed pages, shared UI and dialog components, and a typed API client. Backend access is centralized in `api/client.ts`; mock mode is explicitly labeled in the environment capsule, and live failures are surfaced without falling back to mock data.

GitHub and Google Calendar connector views are read-only. Cortexstone Notes is the only connector with create, update, and delete operations. `POST /api/v1/actions/validate` is policy validation only and never executes a proposal.

Keep authorization and provider credentials on the backend. The browser must not persist action payloads, provider tokens, or user identity.
