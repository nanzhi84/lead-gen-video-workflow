"""G3: publish-attempt and publish-package funnel emission helpers.

Covers the funnel-write helpers in ``apps.api.services.publishing`` directly
against the in-memory ``Repository`` (no FastAPI ``Request`` / DB wiring needed).
"""

from __future__ import annotations

from apps.api.services.publishing import (
    _publish_run_ids,
    _record_publish_attempt_funnel,
)
from packages.core.contracts import (
    ArtifactKind,
    ArtifactRef,
    FinishedVideo,
    PublishAttempt,
    PublishAttemptStatus,
    PublishBatchItemVm,
    PublishBatchVm,
)
from packages.core.storage.repository import Repository


def _seed_finished_video_and_package(repo: Repository) -> tuple[str, str]:
    video_artifact = ArtifactRef(
        artifact_id="art_video",
        kind=ArtifactKind.video_finished,
        uri="local://x/video.mp4",
    )
    finished = FinishedVideo(
        id="fv_1",
        case_id="case_demo",
        run_id="run_1",
        title="Funnel video",
        video_artifact=video_artifact,
    )
    repo.finished_videos[finished.id] = finished
    package = repo.create_publish_package_from_finished_video(finished, title="pkg")
    return finished.id, package.id


def test_publish_run_ids_resolves_run_and_job_from_package():
    repo = Repository()
    # Seed a run so job_id can be resolved off the finished video's run.
    finished_id, package_id = _seed_finished_video_and_package(repo)
    # No run row -> job_id is None but run_id still flows from the finished video.
    run_id, job_id = _publish_run_ids(repo, package_id)
    assert run_id == "run_1"
    assert job_id is None


def test_publish_run_ids_handles_detached_package():
    repo = Repository()
    assert _publish_run_ids(repo, None) == (None, None)
    assert _publish_run_ids(repo, "missing_pkg") == (None, None)


def _attempt(status: PublishAttemptStatus, package_id: str) -> tuple[PublishBatchVm, PublishBatchItemVm, PublishAttempt]:
    item = PublishBatchItemVm(id="item_1", publish_package_id=package_id, platform="xiaovmao", title="t")
    batch = PublishBatchVm(id="batch_1", items=[item])
    attempt = PublishAttempt(
        id="att_1",
        batch_id=batch.id,
        item_id=item.id,
        platforms=["xiaovmao"],
        status=status,
        adapter_id="sandbox.publish",
    )
    return batch, item, attempt


def test_record_attempt_funnel_emits_publish_started_and_published():
    repo = Repository()
    _, package_id = _seed_finished_video_and_package(repo)
    batch, item, attempt = _attempt(PublishAttemptStatus.published, package_id)
    _record_publish_attempt_funnel(repo, batch, item, attempt)
    types = {e.event_type for e in repo.yield_events.values()}
    # §9.5 spec strings: publish_started -> published (true-yield success).
    assert "publish_started" in types
    assert "published" in types
    assert "publish_failed" not in types
    # ``published`` must carry run linkage so it is run-scoped for true yield.
    published = next(e for e in repo.yield_events.values() if e.event_type == "published")
    assert published.run_id == "run_1"


def test_record_attempt_funnel_emits_publish_failed():
    repo = Repository()
    _, package_id = _seed_finished_video_and_package(repo)
    batch, item, attempt = _attempt(PublishAttemptStatus.failed, package_id)
    _record_publish_attempt_funnel(repo, batch, item, attempt)
    types = {e.event_type for e in repo.yield_events.values()}
    assert "publish_started" in types
    assert "publish_failed" in types
    assert "published" not in types


def test_record_attempt_funnel_dry_run_only_publish_started():
    repo = Repository()
    _, package_id = _seed_finished_video_and_package(repo)
    batch, item, attempt = _attempt(PublishAttemptStatus.manual_review_ready, package_id)
    _record_publish_attempt_funnel(repo, batch, item, attempt)
    types = {e.event_type for e in repo.yield_events.values()}
    assert types == {"publish_started"}
