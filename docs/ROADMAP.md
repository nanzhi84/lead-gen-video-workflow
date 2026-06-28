# Roadmap

Last refreshed: 2026-06-28.

This roadmap tracks current priorities only. Historical milestone diaries were
removed because their lasting facts now live in `README.md`, `docs/modules.md`,
`docs/operations.md`, and the live code.

## Current Baseline

- Contract-first remains the architectural spine: FastAPI OpenAPI -> generated
  frontend schema, with shared Pydantic contracts under `packages/core/contracts`.
- SQLAlchemy is the default storage backend. Memory storage is a test/demo path.
- The production workflow has three templates:
  `digital_human_v2`, `broll_only_v1`, and `seedance_t2v_v1`.
- API, worker, frontend, and connector entrypoints are listed in
  `docs/modules.md`.
- Hosted CI has three jobs: `unit`, `integration`, and `frontend`; local parity
  gate is `scripts/ci_gate.sh`.

## Active Priorities

| Priority | Area | Why it matters | Current source |
| --- | --- | --- | --- |
| P0 | Keep API contract drift impossible | Every API shape change must regenerate OpenAPI and frontend types. | `scripts/export_openapi.py`, `apps/web/package.json`, `.github/workflows/ci.yml` |
| P0 | Preserve SQL/Temporal validation | Production-like behavior depends on DB integration and Temporal tests, not only the memory path. | `tests/integration`, `tests/temporal`, `scripts/ci_gate.sh` |
| P1 | Keep provider governance explicit | Real provider calls require profile + active secret; sandbox fallback must remain opt-in. | `packages/ai/gateway`, `packages/ai/providers`, `packages/core/storage/secret_store.py` |
| P1 | Keep ObjectStore tiers shared where needed | Temporal workers need readable durable and ephemeral artifacts across activities. | `packages/core/storage/object_store_env.py`, `docs/operations.md` |
| P1 | Keep docs current and module-based | Dated implementation plans should not become competing truth sources. | `docs/README.md`, `docs/modules.md`, `docs/operations.md` |
| P2 | Continue reducing compatibility wrappers | Remove dead helpers only with reference scans plus type/build/test evidence. | `docs/repo-cleanup-inventory.md` |

## Documentation Rules

- Do not recreate per-milestone diary folders for completed work.
- Keep current architecture in `docs/modules.md`.
- Keep operational commands in `docs/operations.md`.
- Keep unresolved spec or architecture decisions in `docs/spec-questions.md`.
- Keep cleanup evidence in the three `docs/repo-cleanup-*` files until PR #61
  is merged or superseded.

## Deferred Work

These items are intentionally not part of the documentation cleanup:

- Behavior-changing provider, Temporal, or pipeline refactors.
- DB migration rewrites.
- Public API route deletions.
- Generated OpenAPI/schema edits without regeneration.
