# Spec Decisions

Last refreshed: 2026-06-28.

This file keeps decisions that still affect current contracts or operations.
Resolved items remain here only when they guard against future drift.

## ArtifactKind Supplement: `uploaded.file` / `import.mapping`

`uploaded.file` and `import.mapping` remain valid persisted artifact kinds for
clean-slate continuity.

- `uploaded.file` maps to `UploadedFileArtifact`.
- `import.mapping` maps to `ImportMappingArtifact`.

Do not remove these enum values without a migration that replaces existing
upload/import references.

## Hosted CI

GitHub Actions is the hosted CI gate for this repository. `scripts/ci_gate.sh`
is the local equivalent and should continue to mirror the important hosted
checks: default pytest, OpenAPI drift check, frontend type generation/build, DB
integration tests, and Temporal tests.

## Idempotency Replay Status

Spec §32.11 defines idempotency-key hits as HTTP 200 responses returning the
original job/run, plus `Idempotency-Replayed: true`.

Do not change replay responses back to the original creation status (`201` or
`202`) unless the spec is changed first.
