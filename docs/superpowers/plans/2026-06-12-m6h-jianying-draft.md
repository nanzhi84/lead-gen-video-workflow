# M6h Jianying Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate real Jianying draft zip packages from finished videos, timeline, subtitles, audio, and media assets.

**Architecture:** Keep Jianying draft JSON generation in a focused production builder. API/repository code gathers local artifact context and stores the resulting zip through ObjectStore.

**Tech Stack:** Python, pytest, ObjectStore, ffprobe helpers, React/TypeScript.

---

### Task A: Builder

**Files:**
- Create: `packages/production/jianying_draft.py`
- Test: `tests/production/test_jianying_draft_builder.py`

- [ ] Write a failing structure test that unzips the package and checks `draft_content.json`, `draft_meta_info.json`, staged media, video/audio/subtitle tracks, subtitle count, and microsecond timeranges.
- [ ] Implement `JianyingDraftBuilder` with original pyJianYingDraft field names for materials, tracks, segments, supporting files, and meta files.
- [ ] Run the focused builder test and full pytest.
- [ ] Commit Task A if git permits.

### Task B: Artifacts

**Files:**
- Modify: `packages/production/sqlalchemy_repository.py`
- Modify: `apps/api/services/finished_videos.py`
- Test: `tests/golden/test_video_workflow.py`

- [ ] Add failing assertions that editor handoff and Jianying draft artifacts have real package URIs and manifests.
- [ ] Wire builder outputs into repository and in-memory endpoint fallback.
- [ ] Generate editor handoff zip with a manifest and real asset list.
- [ ] Run focused tests and full pytest.
- [ ] Commit Task B if git permits.

### Task C: Frontend

**Files:**
- Modify: `apps/web/src/components/editor-handoff/EditorHandoffActions.tsx`
- Modify if generated: `apps/web/src/api/schema.d.ts`

- [ ] Display tracks summary, draft name, and real package download status from manifest fields.
- [ ] Run frontend typecheck and build.
- [ ] Export OpenAPI and sync schema if backend contract shape changes.
- [ ] Commit Task C if git permits.

### Task D: Verification

**Files:**
- Existing tests only unless a gap remains.

- [ ] Run the required full pytest command.
- [ ] Run frontend `tsc` and build.
- [ ] Inspect final zip structure and summarize copied JSON fields and user-side Jianying desktop verification steps.
