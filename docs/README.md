# Documentation Index

Last refreshed: 2026-06-28.

This directory keeps current product, architecture, operations, and cleanup
evidence. It intentionally no longer keeps historical milestone diaries,
multi-agent planning transcripts, or dated implementation drafts once their
current facts have been folded into the files below.

## Current Sources

| Need | Source | Scope |
| --- | --- | --- |
| Product and capability baseline | [Spec](树影_Cutagent_CleanSlate重写Spec_v3_2026-06-11.md) | Raw clean-slate spec. Treat Spec §2 and §34 as the capability and API baseline unless a later contract change explicitly supersedes them. |
| Quick repo orientation | [README.md](../README.md) | Setup, major capabilities, commands, env, and CI. |
| Module map | [docs/modules.md](modules.md) | Current code layout by app/package, verified from live routes, worker entrypoints, pipeline node order, provider registry, and migrations. |
| Operations runbook | [docs/operations.md](operations.md) | Local infra, ObjectStore/OSS, DashScope ASR prerequisites, provider balance refresh, media cleanup scripts, and validation commands. |
| Roadmap | [docs/ROADMAP.md](ROADMAP.md) | Current engineering priorities only. Historical M1/M2/M6 diary files were removed. |
| Spec decisions | [docs/spec-questions.md](spec-questions.md) | Open or resolved architecture/spec decisions that still matter. |
| Cleanup evidence | [log](repo-cleanup-log.md), [inventory](repo-cleanup-inventory.md), [PR body](repo-cleanup-pr.md) | Review evidence for the repository hygiene PR. |

## Documentation Policy

- Prefer current, module-based documents over dated implementation diaries.
- Cite live code paths and commands. Avoid absolute local paths and stale branch
  names.
- Keep setup and operations examples in `README.md` or `docs/operations.md`, not
  scattered across feature plans.
- Do not hand-edit generated API files. Regenerate from FastAPI:

```bash
uv run --extra dev python scripts/export_openapi.py
( cd apps/web && npm run generate:api )
```

- Add new long design docs only when the work is still under active review. Once
  implemented, fold the lasting facts into `docs/modules.md`,
  `docs/operations.md`, or `docs/ROADMAP.md`.
