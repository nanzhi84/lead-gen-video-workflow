# Cutagent Clean-Slate

This is a clean-room implementation of the Case-first digital human content production system described in:

`C:\Users\Nanzhi\Desktop\树影_Cutagent_CleanSlate重写Spec_v3_2026-06-11.md`

The first implementation slice is contract-first:

- FastAPI is the OpenAPI source of truth.
- Pydantic v2 models live under `packages/core/contracts`.
- SQLAlchemy 2 metadata and Alembic migrations live under `packages/core/storage`.
- Workflow execution goes through a runtime adapter and node runner.
- Provider calls go through capability plugins, with sandbox providers for local development.
- The production pipeline emits typed artifacts, reports, usage records, and degradations.
- Every endpoint from Spec section 34 is registered in OpenAPI.
- Web TypeScript API types are generated from OpenAPI with `openapi-typescript`.

Local seed accounts:

- `admin@local.cutagent` / `local-admin`
- `viewer@local.cutagent` / `local-viewer`

Run locally:

```powershell
python -m uvicorn apps.api.main:app --reload --port 8000
```

Run tests:

```powershell
python -m pytest
```

Prepare infrastructure:

```powershell
docker compose up -d postgres redis minio temporal temporal-ui
python scripts/bootstrap_database.py
```

The bundled PostgreSQL service binds to host port `55432` by default so it does not collide with an existing local Postgres on `5432`.

Run API with the SQLAlchemy backend initialized:

```powershell
$env:CUTAGENT_STORAGE_BACKEND='sqlalchemy'
python -m uvicorn apps.api.main:app --reload --port 8000
```

Database integration tests:

```powershell
$env:CUTAGENT_RUN_DB_TESTS='1'
$env:CUTAGENT_STORAGE_BACKEND='sqlalchemy'
python -m pytest tests/integration
```

Refresh frontend API types:

```powershell
cd apps/web
npm run generate:api
npm run build
```

Current important gaps before production completion:

- API still defaults to the in-process repository; SQLAlchemy schema, migration, seed, viewer-authenticated Case reads plus operator-guarded Case create/update/query filters, operator-guarded Case Agent source/import/run/adopt/memory/reflection/script-generation writes, Case Agent brief/draft reads, Case memory proposal approve/reject and knowledge reads, reflection run sandbox flow, auth login/session/register/logout/me update/change-password, admin-only user and registration-code management, admin-guarded secret list/create/rotate/disable, operator-guarded upload/artifact creation, operator-guarded workflow creation/control, process-local Idempotency-Key replay/conflict handling for write APIs, job/run/node/artifact/report workflow snapshot persistence, workflow outbox event creation and event-token run validation, provider invocation, usage meter, and prompt invocation persistence from sandbox workflow runs, operator-guarded media asset list/detail/create/preview and annotation editor read/patch/rerun, operator/admin-guarded voice profile list/filter/clone/design/preview/update/delete, admin-guarded prompt template/version/binding/experiment flows and filters, admin-guarded provider profile/capability/balance filters, admin-guarded provider price catalogs/items/active filters, admin-guarded provider billing reconciliation audit, operator-guarded publishing package/batch/item/attempt flows, operator/admin-guarded finished-video import/list/detail/preview/editor-handoff/draft handoff/delete, publish-record creation, operator-guarded performance metric import plus rollup/attribution, operator-guarded import batch target types, Ops dashboard/cost/budget/alert reads and writes, admin-guarded budget writes and audit reads, operator-guarded alert/quality/approval flows, and quality/approval/audit governance flows are working, but most remaining endpoint write/read paths still need to be moved onto DB sessions.
- Temporal is represented by the runtime boundary and worker contract, but the production Temporal SDK adapter is not yet active.
- Idempotency-Key replay is currently API-process local; production still needs DB-backed idempotency records for cross-process and restart safety.
- Media processing and external providers are sandbox implementations.
- Permissions are implemented in the auth service and enforced by default-login middleware for non-auth APIs plus route role guards for viewer/operator/admin matrix paths, including uploads, secrets, Cases, workflow creation/control, Case Agent writes, prompts, provider config/price/balance/reconcile, budget writes, audit reads, publishing, imports, performance metric import, media edit/voice/finished-video operations, alert actions, quality checks, and approval routes.
