# Module Map

Last refreshed: 2026-06-28.

This map describes the current repository shape from live source files, not from
old milestone plans. It is intentionally concise and should be updated when a
module boundary, runtime entrypoint, or contract source changes.

## System Invariants

- FastAPI is the OpenAPI source of truth. The generated frontend files are
  `apps/web/src/api/openapi.json` and `apps/web/src/api/schema.d.ts`.
- Shared domain contracts live under `packages/core/contracts`.
- DB migrations live only in
  `packages/core/storage/alembic/versions/`; `packages/migrations` is only a
  directory convention placeholder.
- Default storage backend is SQLAlchemy. `memory` is for tests and demos.
- Temporal worker is a separate long-running process. Changes in
  `packages/production` or node code require a worker restart.
- External AI/media calls go through `ProviderGateway` by capability. Production
  prompts resolve through `PromptRegistry`.
- Provider keys belong in `SecretStore`/`ProviderProfile`, not env or code.
- Durable and ephemeral ObjectStore buckets must be separate when tiered storage
  is enabled.

## Apps

| App | Entry points | Responsibility |
| --- | --- | --- |
| `apps/api` | `apps/api/main.py`, `apps/api/app.py` | FastAPI service, auth middleware, dependency wiring, router registration, outbox dispatcher, provider/prompt/runtime state. |
| `apps/worker` | `python -m apps.worker`, `apps/worker/main.py` | Temporal worker for `cutagent-production` or the configured task queue. Builds provider gateway, prompt registry, workflow runtime, and activity context. |
| `apps/web` | `apps/web/src/main.tsx`, `apps/web/src/App.tsx`, `apps/web/src/routes.ts` | React/Vite console. Routes cover studio, settings, library, analytics, account, prompt ops, publish ops, and ops pages. |
| `apps/connectors` | `apps/connectors/oceanengine/cli.py` | Offline OceanEngine/XLSX ingestion and normalization. Runs outside the API process. |

## API Surface

Router registration is centralized in `apps/api/app.py`:

- `core`: health and Prometheus metrics.
- `auth`: register, login, logout, session, users, generation defaults, registration codes.
- `uploads`: prepare/complete/cancel/get upload sessions.
- `secrets`: secret previews, create, rotate, disable.
- `cases`: Case CRUD.
- `creative`: reference extraction and cookie-refresh compatibility endpoint.
- `jobs_runs`: digital-human job creation, batch creation, run detail/control, artifacts, reports, run event token, `/ws/runs/{run_id}`.
- `media`: media assets, usage ranking, annotation batch/editor/trim/rerun, asset content and preview URLs.
- `voices`: voice list, sync, clone, preview, status refresh, patch, delete.
- `prompts`: prompt templates, versions, review/publish/rollback, bindings, experiments.
- `providers`: provider profiles, capabilities, price catalogs, usage, balances, billing reconciliation.
- `case_agent`: script drafts, performance, metrics import, memory-backed generation.
- `case_rubric`: rubric, calibration, predictions, pending retro, score outcomes.
- `finished_videos`: finished video list/detail/preview/download, editor handoff, Jianying draft.
- `publish_accounts`: clients, accounts, platform sessions, login stream websocket.
- `publishing`: publish packages, batches, items, attempts, submit/retry/copy/cover helpers.
- `ops`: dashboard, cost/yield/provider metrics, failure taxonomy, alerts, budgets, quality checks, approvals, audit events.
- `imports`: generic import batches.

The generated OpenAPI snapshot is checked into
`apps/web/src/api/openapi.json`. Regenerate it after any API shape change; do
not hand-edit the snapshot or `schema.d.ts`.

## Packages

| Package | Current role |
| --- | --- |
| `packages/core` | Contracts, config, auth, observability, storage, migrations, ObjectStore, SecretStore, workflow runtime adapter contracts. |
| `packages/ai` | Provider gateway, provider runtime repository, provider limiter, prompt registry, real provider plugins, sandbox provider. |
| `packages/creative` | Case repositories, learning/evolution, rubric, reference extraction helpers. |
| `packages/media` | Media assets, annotation pipeline, audio alignment/loudness/silence, ffmpeg wrapper, cover/frame helpers, rendering timeline, voice provider bridge. |
| `packages/planning` | Material matching, deterministic selection, editing/narration unit helpers, ledger-aware choices. |
| `packages/production` | Digital-human workflow engine, node handlers, node sequence, reuse/resume, runtime SQL repository, ephemeral GC, editor/Jianying artifacts. |
| `packages/publishing` | Publishing repository, account/session models, platform connector boundary, XiaoVmao CDP integration. |
| `packages/ops` | Cost/yield metrics, provider balance service, budgets, alerts, circuit breaker, SQL mappers/repository. |
| `packages/migrations` | Placeholder only; do not put Alembic files here. |

## Production Workflow Templates

The canonical node order is `packages/production/pipeline/node_sequence.py`.

`digital_human_v2`:

```text
ValidateRequest -> LoadCaseContext -> ResolveCreativeIntent -> TTS
-> MaterialPackPlanning -> NarrationAlignment -> PortraitPlanning
-> BrollPlanning -> StylePlanning -> TimelinePlanning -> PortraitTrackBuild
-> LipSync -> RenderFinalTimeline -> SubtitleAndBgmMix
-> ExportFinishedVideo -> FinalizeRunReport
```

`broll_only_v1` replaces portrait/lipsync nodes with B-roll coverage and base
rendering nodes. `seedance_t2v_v1` uses:

```text
ValidateRequest -> LoadCaseContext -> SeedanceGenerateVideo
-> ExportSeedanceVideo -> FinalizeRunReport
```

Node handlers are dispatched in `packages/production/pipeline/digital_human.py`
through `NODE_HANDLERS`.

## Provider Boundary

Real provider plugins are registered in `packages/ai/providers/__init__.py`:

- MiniMax TTS.
- Volcengine TTS.
- DashScope ASR, VLM, LLM, Omni, and VideoReTalk.
- RunningHub HeyGem.
- Ark Seedance.
- OpenAI image generation.

The gateway always includes the sandbox provider. Real paths require matching
provider profiles and active secrets unless sandbox fallback is explicitly
allowed.

## Storage And Runtime

- SQLAlchemy storage is configured through `CUTAGENT_STORAGE_BACKEND=sqlalchemy`
  or `postgres` plus `CUTAGENT_DATABASE_URL`.
- Alembic migrations live in `packages/core/storage/alembic/versions/`; the
  current single head is `0022_drop_publish_hashtags`.
- Temporal runtime uses `CUTAGENT_WORKFLOW_RUNTIME=temporal`,
  `CUTAGENT_TEMPORAL_ADDRESS`, `CUTAGENT_TEMPORAL_NAMESPACE`, and
  `CUTAGENT_TEMPORAL_TASK_QUEUE`.
- Object storage is configured in `packages/core/storage/object_store_env.py`
  and `packages/core/config/settings.py`. Durable output and ephemeral scratch
  tiers should use separate buckets.

## Tests And CI

- Default tests: `python -m pytest -q`.
- DB integration tests: `CUTAGENT_RUN_DB_TESTS=1 python -m pytest -q tests/integration`.
- Temporal tests: `CUTAGENT_RUN_TEMPORAL_TESTS=1 python -m pytest -q tests/temporal`.
- Full local gate: `scripts/ci_gate.sh`.
- Hosted CI is `.github/workflows/ci.yml` with `unit`, `integration`, and
  `frontend` jobs.
