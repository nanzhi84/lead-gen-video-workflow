# Operations Runbook

Last refreshed: 2026-06-28.

This file replaces the old scattered ops notes. It covers only current commands
and settings that map to live code.

## Local Startup

Recommended path:

```bash
cp .env.example .env.local
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
( cd apps/web && npm install )
scripts/dev_up.sh up
```

Useful dev commands:

```bash
scripts/dev_up.sh status
scripts/dev_up.sh logs api
scripts/dev_up.sh logs worker
scripts/dev_up.sh logs web
scripts/dev_up.sh down
scripts/dev_up.sh down --infra
```

Postgres is exposed on host port `55432`. MinIO uses `9000/9001`, Temporal uses
`7233`, and Temporal UI uses `8080`.

## Database

Bootstrap and seed:

```bash
python scripts/bootstrap_database.py
```

Migration only:

```bash
python scripts/migrate.py
```

The SQLAlchemy backend requires:

```bash
export CUTAGENT_STORAGE_BACKEND=sqlalchemy
export CUTAGENT_DATABASE_URL=postgresql+psycopg://cutagent:cutagent@localhost:55432/cutagent
```

## Temporal Worker

API and worker must use the same namespace and task queue:

```bash
export CUTAGENT_WORKFLOW_RUNTIME=temporal
export CUTAGENT_TEMPORAL_ADDRESS=localhost:7233
export CUTAGENT_TEMPORAL_NAMESPACE=default
export CUTAGENT_TEMPORAL_TASK_QUEUE=cutagent-production
python -m apps.worker
```

Restart the worker after changing `packages/production`, pipeline nodes,
provider wiring, prompt registry behavior, or media helpers used by nodes.

## ObjectStore

Local durable storage:

```bash
export CUTAGENT_OBJECTSTORE_BACKEND=local
export CUTAGENT_LOCAL_OBJECTSTORE_PATH=.data/objectstore
```

Local MinIO/S3-compatible durable and ephemeral tiers:

```bash
export CUTAGENT_OBJECTSTORE_TIERED=1
export CUTAGENT_OBJECTSTORE_BACKEND=s3
export CUTAGENT_OBJECTSTORE_ENDPOINT=http://127.0.0.1:9000
export CUTAGENT_OBJECTSTORE_BUCKET=cutagent-local
export CUTAGENT_OBJECTSTORE_ACCESS_KEY=minioadmin
export CUTAGENT_OBJECTSTORE_SECRET_KEY=minioadmin
export CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE=path

export CUTAGENT_EPHEMERAL_OBJECTSTORE_BACKEND=s3
export CUTAGENT_EPHEMERAL_OBJECTSTORE_ENDPOINT=http://127.0.0.1:9000
export CUTAGENT_EPHEMERAL_OBJECTSTORE_BUCKET=cutagent-ephemeral
export CUTAGENT_EPHEMERAL_OBJECTSTORE_ACCESS_KEY=minioadmin
export CUTAGENT_EPHEMERAL_OBJECTSTORE_SECRET_KEY=minioadmin
export CUTAGENT_EPHEMERAL_OBJECTSTORE_ADDRESSING_STYLE=path
```

Keep durable and ephemeral bucket names different. Temporal workers need shared
ephemeral storage when more than one worker or host can run activities.

## Aliyun OSS And DashScope ASR

DashScope Paraformer downloads audio from the URL submitted in `file_urls`.
Strict timestamp alignment therefore needs a public, DashScope-reachable HTTPS
object URL. Local `127.0.0.1` MinIO URLs are not reachable from DashScope.

Aliyun OSS example:

```bash
export CUTAGENT_OBJECTSTORE_BACKEND=s3
export CUTAGENT_OBJECTSTORE_ENDPOINT=https://oss-cn-<region>.aliyuncs.com
export CUTAGENT_OBJECTSTORE_BUCKET=<bucket>
export CUTAGENT_OBJECTSTORE_ACCESS_KEY=<access-key-id>
export CUTAGENT_OBJECTSTORE_SECRET_KEY=<access-key-secret>
export CUTAGENT_OBJECTSTORE_REGION=oss-cn-<region>
export CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE=virtual
export CUTAGENT_OBJECTSTORE_MULTIPART_THRESHOLD_MB=8
export CUTAGENT_OBJECTSTORE_MULTIPART_CHUNK_MB=8
export CUTAGENT_OBJECTSTORE_MAX_CONCURRENCY=4
export CUTAGENT_OBJECTSTORE_CONNECT_TIMEOUT=10
export CUTAGENT_OBJECTSTORE_READ_TIMEOUT=120
export CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS=5
```

The bucket may remain private if Cutagent passes presigned HTTPS URLs to the
provider.

## Provider Balances

Current endpoints:

- `GET /api/providers/balances`
- `POST /api/providers/balances/refresh`

The optional background poller is controlled by:

```bash
export CUTAGENT_BALANCE_POLLER_ENABLED=1
export CUTAGENT_BALANCE_POLL_INTERVAL_SECONDS=900
export CUTAGENT_BALANCE_REQUEST_TIMEOUT_SECONDS=10
```

Profiles without a readable `secret_ref` are reported as `unconfigured`.
Providers without a balance API are reported as `unsupported`. HTTP failures are
stored as sanitized `error` details.

## Media Cleanup Scripts

Generated local ObjectStore GC:

```bash
python scripts/gc_objectstore.py --max-age-hours 24
python scripts/gc_objectstore.py --max-age-hours 24 --apply
```

Dangling material cleanup checks that media asset source objects exist before
deleting DB rows. It is dry-run by default and refuses implausibly large deletes:

```bash
python scripts/clean_dangling_materials.py
python scripts/clean_dangling_materials.py --apply
```

Sync production material metadata into a local DB without annotations:

```bash
python scripts/sync_materials.py --prod-dsn postgresql://cutagent:cutagent@<prod>:55432/cutagent
python scripts/sync_materials.py --prod-dsn postgresql://cutagent:cutagent@<prod>:55432/cutagent --apply
```

## Validation

Contract and generated client:

```bash
uv run --extra dev python scripts/export_openapi.py
( cd apps/web && npm run generate:api )
git diff --exit-code -- apps/web/src/api/openapi.json apps/web/src/api/schema.d.ts
```

Broad local checks:

```bash
uv run --extra dev ruff check .
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  uv run --extra dev python -m pytest -q
( cd apps/web && npx tsc -p tsconfig.json --noEmit --noUnusedLocals --noUnusedParameters )
( cd apps/web && npm run build )
```

Full local gate:

```bash
scripts/ci_gate.sh
```
