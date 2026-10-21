# API process

The FastAPI ASGI application is bootstrapped in `src/cortexstone/api/main.py` and runs with:

```powershell
py -m uvicorn cortexstone.api.main:app --reload
```

Use `/health/live` and `/health/ready` for operational probes. Add product routes beneath `/api/v1`; keep handlers thin and do not execute tools directly from routes or allow model responses to authorize actions. See [development setup and integration conventions](../../docs/DEVELOPMENT.md).
