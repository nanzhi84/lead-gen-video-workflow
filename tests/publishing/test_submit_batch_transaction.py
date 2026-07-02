"""Regression: ``submit_batch`` must not hold an open DB transaction while the
publish runner (小V猫 CDP polling up to 15min + ~100MiB media download) runs.

The runner is invoked in a no-transaction window between transaction A
(read/validate/snapshot) and transaction B (write terminal statuses), so a single
submit never pins a pooled connection for the duration of a publish.
"""

from __future__ import annotations

from packages.core.contracts import (
    ArtifactKind,
    ArtifactRef,
    PublishDefaults,
    SubmitPublishBatchRequest,
)
from packages.core.storage.database import (
    PublishBatchItemRow,
    PublishBatchRow,
    PublishPackageRow,
)
from packages.core.storage.repository import new_id
from packages.publishing.platform_adapter import PublishOutcome
from packages.publishing.sqlalchemy_repository import SqlAlchemyPublishingRepository


class _SessionTracker:
    """Wraps a sessionmaker and counts how many sessions are open at any moment."""

    def __init__(self, inner):
        self._inner = inner
        self.active = 0
        self.max_active = 0

    def __call__(self):
        return _TrackedSession(self)

    def _open_inner(self):
        return self._inner()


class _TrackedSession:
    def __init__(self, tracker: _SessionTracker):
        self._tracker = tracker
        self._session = None

    def __enter__(self):
        self._session = self._tracker._open_inner()
        entered = self._session.__enter__()
        self._tracker.active += 1
        self._tracker.max_active = max(self._tracker.max_active, self._tracker.active)
        return entered

    def __exit__(self, *exc):
        self._tracker.active -= 1
        return self._session.__exit__(*exc)


def _seed_batch(session_factory) -> tuple[str, str]:
    video_artifact = ArtifactRef(
        artifact_id=new_id("art"),
        kind=ArtifactKind.video_finished,
        uri="local://x/video.mp4",
    ).model_dump(mode="json")
    package_id = new_id("pkg")
    batch_id = new_id("pub_batch")
    item_id = new_id("pub_item")
    with session_factory() as session:
        session.add(
            PublishPackageRow(
                id=package_id,
                case_id="case_demo",
                video_artifact=video_artifact,
                platform_defaults=PublishDefaults(title="t", description="d").model_dump(mode="json"),
            )
        )
        session.add(PublishBatchRow(id=batch_id, status="review_ready"))
        session.flush()
        session.add(
            PublishBatchItemRow(
                id=item_id,
                batch_id=batch_id,
                publish_package_id=package_id,
                platform="douyin",
                title="t",
                status="review_ready",
                selected=True,
            )
        )
        session.commit()
    return batch_id, item_id


def test_submit_batch_runs_publish_runner_outside_open_transaction(db_session_factory):
    batch_id, item_id = _seed_batch(db_session_factory)
    tracker = _SessionTracker(db_session_factory)
    repo = SqlAlchemyPublishingRepository(tracker)

    observed: dict[str, int] = {}

    def probe_runner(item, package) -> PublishOutcome:
        # By the time the runner is called, transaction A has committed and closed,
        # so no repository session is open (the expensive publish work holds no lock).
        observed["active_during_runner"] = tracker.active
        return PublishOutcome(
            success=True,
            adapter_id="sandbox.publish",
            results=[{"platform": getattr(item, "platform", None), "success": True}],
        )

    result = repo.submit_batch(batch_id, SubmitPublishBatchRequest(), publish_runner=probe_runner)

    assert observed["active_during_runner"] == 0
    assert tracker.max_active >= 1  # the repo really did open sessions
    assert result is not None
    assert result.status == "completed"
    statuses = {item.id: item.status for item in result.items}
    assert statuses[item_id] == "published"


def test_submit_batch_marks_item_failed_when_runner_raises(db_session_factory):
    batch_id, item_id = _seed_batch(db_session_factory)
    repo = SqlAlchemyPublishingRepository(db_session_factory)

    def raising_runner(item, package) -> PublishOutcome:
        raise RuntimeError("publish exploded")

    result = repo.submit_batch(batch_id, SubmitPublishBatchRequest(), publish_runner=raising_runner)

    assert result is not None
    assert result.status == "partial_failed"
    statuses = {item.id: item.status for item in result.items}
    assert statuses[item_id] == "publish_failed"
