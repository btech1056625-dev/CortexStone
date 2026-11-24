# Operational runbooks

## Local startup

Requirements: Python 3.12 or 3.13, Docker Desktop, and Docker Compose v2.

```powershell
Copy-Item .env.example .env
docker compose up --build --wait
docker compose ps
docker compose exec api python -m alembic current
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
```

Stop local services with `docker compose down`. Use `docker compose down --volumes` only when deleting the named PostgreSQL data volume is intentional.

## Migration

Migrations run through the `migrate` Compose service before the API starts.

```powershell
docker compose run --rm migrate
docker compose exec api python -m alembic current
docker compose exec api python -m alembic history
```

Before upgrading an existing database, create a backup and record the target revision. Test upgrade and downgrade procedures against a disposable copy before using them in production.

## Health troubleshooting

```powershell
docker compose ps
docker compose logs db migrate api
```

- `/health` checks process availability.
- `/ready` checks database connectivity and verifies the applied Alembic revisions match the packaged migration heads.
- Model providers are feature-scoped rather than global readiness dependencies; chat reports unavailable when a required provider is not configured.
- An authentication 503 means OIDC configuration or provider availability is not usable.
- A protected-route 401 means the bearer credential is missing or invalid.

## Credential rotation

1. Create or obtain the replacement secret outside the repository.
2. Update the deployment environment through the secret manager.
3. Restart affected API/worker processes.
4. Verify OIDC JWKS/key behavior or Groq/Google AI Studio/database connectivity.
5. Revoke the previous credential only after the replacement is confirmed.
6. Inspect logs and audit output for unexpected secret exposure.

Never commit `.env`, bearer tokens, model keys, database passwords, or connector credentials.

## Incident triage

1. Capture the request ID and timestamp.
2. Preserve `docker compose ps` and relevant service logs.
3. Stop the affected public route or credential if an active secret exposure is suspected.
4. Verify memory-owner isolation and recent action/audit records.
5. Rotate credentials and invalidate affected approvals or grants.
6. Restore from a known-good database backup if persistence integrity is in doubt.

## Production gaps

Worker recovery, backup/restore automation, Telegram retries, Guardian scanning, scheduled jobs, and Nebius deployment runbooks require implementation and hosted acceptance evidence before use.
