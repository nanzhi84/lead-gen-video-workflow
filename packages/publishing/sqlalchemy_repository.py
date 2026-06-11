from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import (
    ArtifactRef,
    CreatePublishBatchRequest,
    CreatePublishPackageRequest,
    ErrorCode,
    PatchPublishPackageRequest,
    PatchPublishItemRequest,
    PublishAttempt,
    PublishAttemptDetail,
    PublishBatchItemVm,
    PublishBatchVm,
    PublishDefaults,
    PublishPackage,
    SubmitPublishBatchRequest,
    utcnow,
)
from packages.core.contracts.state_machines import assert_transition
from packages.core.storage.database import (
    ArtifactRow,
    FinishedVideoRow,
    PublishAttemptRow,
    PublishBatchItemRow,
    PublishBatchRow,
    PublishPackageRow,
    PublishRecordRow,
    VideoVersionRow,
)
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError
from packages.publishing.sqlalchemy_mappers import (
    artifact_ref_from_row,
    publish_attempt_row_to_contract,
    publish_batch_row_to_contract,
    publish_item_row_to_contract,
    publish_package_row_to_contract,
    publish_record_row_to_contract,
)


class SqlAlchemyPublishingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_packages(self, *, limit: int = 50) -> list[PublishPackage]:
        with self.session_factory() as session:
            statement = select(PublishPackageRow).order_by(PublishPackageRow.updated_at.desc()).limit(limit)
            return [publish_package_row_to_contract(row) for row in session.scalars(statement)]

    def create_package(self, payload: CreatePublishPackageRequest) -> PublishPackage:
        if payload.source_finished_video_id:
            return self._create_package_from_finished_video(payload)
        if not payload.upload_artifact_id:
            raise NodeExecutionError(ErrorCode.artifact_missing, "Upload artifact is required.")
        return self._create_package_from_upload(payload)

    def _create_package_from_finished_video(self, payload: CreatePublishPackageRequest) -> PublishPackage:
        with self.session_factory() as session:
            finished = session.get(FinishedVideoRow, payload.source_finished_video_id)
            if finished is None:
                raise NodeExecutionError(ErrorCode.artifact_missing, "Finished video is required.")
            row = PublishPackageRow(
                id=new_id("pkg"),
                case_id=finished.case_id,
                source_finished_video_id=finished.id,
                upload_artifact_id=None,
                video_artifact=ArtifactRef.model_validate(finished.video_artifact).model_dump(mode="json"),
                cover_artifact=(
                    ArtifactRef.model_validate(finished.cover_artifact).model_dump(mode="json")
                    if finished.cover_artifact
                    else None
                ),
                platform_defaults=PublishDefaults(
                    title=payload.title,
                    description=payload.description,
                ).model_dump(mode="json"),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return publish_package_row_to_contract(row)

    def _create_package_from_upload(self, payload: CreatePublishPackageRequest) -> PublishPackage:
        with self.session_factory() as session:
            artifact = session.get(ArtifactRow, payload.upload_artifact_id)
            if artifact is None:
                raise NodeExecutionError(ErrorCode.artifact_missing, "Upload artifact is required.")
            row = PublishPackageRow(
                id=new_id("pkg"),
                upload_artifact_id=artifact.id,
                video_artifact=artifact_ref_from_row(artifact).model_dump(mode="json"),
                cover_artifact=None,
                platform_defaults=PublishDefaults(
                    title=payload.title,
                    description=payload.description,
                ).model_dump(mode="json"),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return publish_package_row_to_contract(row)

    def patch_package(self, package_id: str, payload: PatchPublishPackageRequest) -> PublishPackage | None:
        with self.session_factory() as session:
            row = session.get(PublishPackageRow, package_id)
            if row is None:
                return None
            if {"title", "description"} & payload.model_fields_set:
                defaults = PublishDefaults.model_validate(row.platform_defaults)
                defaults_updates = {}
                if "title" in payload.model_fields_set and payload.title is not None:
                    defaults_updates["title"] = payload.title
                if "description" in payload.model_fields_set and payload.description is not None:
                    defaults_updates["description"] = payload.description
                if defaults_updates:
                    row.platform_defaults = defaults.model_copy(update=defaults_updates).model_dump(mode="json")
            if "cover_artifact_id" in payload.model_fields_set:
                if payload.cover_artifact_id:
                    artifact = session.get(ArtifactRow, payload.cover_artifact_id)
                    if artifact is None:
                        raise NodeExecutionError(ErrorCode.artifact_missing, "Cover artifact is required.")
                    row.cover_artifact = artifact_ref_from_row(artifact).model_dump(mode="json")
                else:
                    row.cover_artifact = None
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return publish_package_row_to_contract(row)

    def list_batches(self, *, limit: int = 50, case_id: str | None = None) -> list[PublishBatchVm]:
        with self.session_factory() as session:
            statement = select(PublishBatchRow)
            if case_id:
                batch_ids = (
                    select(PublishBatchItemRow.batch_id)
                    .join(PublishPackageRow, PublishBatchItemRow.publish_package_id == PublishPackageRow.id)
                    .where(PublishPackageRow.case_id == case_id)
                    .distinct()
                )
                statement = statement.where(PublishBatchRow.id.in_(batch_ids))
            statement = statement.order_by(PublishBatchRow.updated_at.desc()).limit(limit)
            rows = list(session.scalars(statement))
            return [publish_batch_row_to_contract(session, row) for row in rows]

    def get_batch(self, batch_id: str) -> PublishBatchVm | None:
        with self.session_factory() as session:
            row = session.get(PublishBatchRow, batch_id)
            return publish_batch_row_to_contract(session, row) if row else None

    def list_attempts(self, batch_id: str, *, limit: int = 50) -> list[PublishAttempt]:
        with self.session_factory() as session:
            statement = (
                select(PublishAttemptRow)
                .where(PublishAttemptRow.batch_id == batch_id)
                .order_by(PublishAttemptRow.created_at.desc(), PublishAttemptRow.id.asc())
                .limit(limit)
            )
            return [publish_attempt_row_to_contract(row) for row in session.scalars(statement)]

    def create_batch(self, payload: CreatePublishBatchRequest) -> PublishBatchVm:
        if not payload.publish_package_ids or not payload.platform_targets:
            raise NodeExecutionError(
                ErrorCode.validation_invalid_options,
                "Publish packages and platform targets are required.",
            )
        with self.session_factory() as session:
            packages: dict[str, PublishPackageRow] = {}
            for package_id in payload.publish_package_ids:
                package = session.get(PublishPackageRow, package_id)
                if package is None:
                    raise NodeExecutionError(ErrorCode.artifact_missing, "Publish package is required.")
                packages[package_id] = package

            batch = PublishBatchRow(id=new_id("pub_batch"), status="draft")
            session.add(batch)
            session.flush()
            for package_id in payload.publish_package_ids:
                defaults = PublishDefaults.model_validate(packages[package_id].platform_defaults)
                for platform in payload.platform_targets:
                    session.add(
                        PublishBatchItemRow(
                            id=new_id("pub_item"),
                            batch_id=batch.id,
                            publish_package_id=package_id,
                            platform=platform,
                            title=defaults.title,
                            description=defaults.description,
                            selected=True,
                            status="uploaded",
                        )
                    )
            session.commit()
            session.refresh(batch)
            return publish_batch_row_to_contract(session, batch)

    def delete_batch(self, batch_id: str) -> bool:
        with self.session_factory() as session:
            batch = session.get(PublishBatchRow, batch_id)
            if batch is None:
                return False
            session.execute(delete(PublishAttemptRow).where(PublishAttemptRow.batch_id == batch_id))
            session.execute(delete(PublishBatchItemRow).where(PublishBatchItemRow.batch_id == batch_id))
            session.delete(batch)
            session.commit()
            return True

    def delete_item(self, item_id: str) -> bool:
        with self.session_factory() as session:
            item = session.get(PublishBatchItemRow, item_id)
            if item is None:
                return False
            session.execute(delete(PublishAttemptRow).where(PublishAttemptRow.item_id == item_id))
            session.delete(item)
            session.commit()
            return True

    def submit_batch(self, batch_id: str, payload: SubmitPublishBatchRequest) -> PublishBatchVm | None:
        with self.session_factory() as session:
            batch = session.get(PublishBatchRow, batch_id)
            if batch is None:
                return None
            statement = (
                select(PublishBatchItemRow)
                .where(PublishBatchItemRow.batch_id == batch_id)
                .order_by(PublishBatchItemRow.created_at.asc(), PublishBatchItemRow.id.asc())
            )
            items = list(session.scalars(statement))
            selected_items = [item for item in items if item.selected]
            if not selected_items:
                raise NodeExecutionError(
                    ErrorCode.validation_invalid_options,
                    "At least one publish item must be selected.",
                )

            batch_status = "review_ready" if payload.dry_run else "completed"
            assert_transition("publish_batch", batch.status, "processing")
            assert_transition("publish_batch", "processing", "review_ready" if payload.dry_run else "publishing")
            if not payload.dry_run:
                assert_transition("publish_batch", "publishing", "completed")
            batch.status = batch_status
            batch.updated_at = utcnow()
            for item in selected_items:
                target_item_status = "review_ready" if payload.dry_run else "published"
                current_item_status = item.status
                for next_status in ["normalizing", "asr_running", "copy_running", "cover_running"]:
                    assert_transition("publish_item", current_item_status, next_status)
                    current_item_status = next_status
                if payload.dry_run:
                    assert_transition("publish_item", current_item_status, "review_ready")
                    current_item_status = "review_ready"
                else:
                    assert_transition("publish_item", current_item_status, "review_ready")
                    current_item_status = "review_ready"
                    assert_transition("publish_item", current_item_status, "publishing")
                    current_item_status = "publishing"
                    assert_transition("publish_item", current_item_status, "published")
                    current_item_status = "published"
                item.status = target_item_status
                item.updated_at = utcnow()
                package = session.get(PublishPackageRow, item.publish_package_id)
                if package is not None and package.case_id:
                    version = None
                    if package.source_finished_video_id:
                        version = session.scalar(
                            select(VideoVersionRow)
                            .where(VideoVersionRow.finished_video_id == package.source_finished_video_id)
                            .order_by(VideoVersionRow.updated_at.desc())
                            .limit(1)
                        )
                    cover_ref = (
                        ArtifactRef.model_validate(package.cover_artifact) if package.cover_artifact else None
                    )
                    session.add(
                        PublishRecordRow(
                            id=new_id("pub_record"),
                            case_id=package.case_id,
                            video_version_id=version.id if version else None,
                            publish_package_id=package.id,
                            publish_batch_id=batch.id,
                            platform=item.platform,
                            status=target_item_status,
                            cover_artifact_id=cover_ref.artifact_id if cover_ref else None,
                            published_at=utcnow() if target_item_status == "published" else None,
                        )
                    )
                attempt_status = "published" if not payload.dry_run else "manual_review_ready"
                assert_transition("publish_attempt", "created", attempt_status)
                session.add(
                    PublishAttemptRow(
                        id=new_id("pub_attempt"),
                        batch_id=batch.id,
                        item_id=item.id,
                        platforms=[item.platform],
                        manual_review=payload.dry_run,
                        status=attempt_status,
                        adapter_id="sandbox.publish",
                        external_task_id=None,
                        results=[],
                        finished_at=utcnow() if attempt_status == "published" else None,
                    )
                )
            session.commit()
            session.refresh(batch)
            return publish_batch_row_to_contract(session, batch)

    def patch_item(self, item_id: str, payload: PatchPublishItemRequest) -> PublishBatchItemVm | None:
        with self.session_factory() as session:
            row = session.get(PublishBatchItemRow, item_id)
            if row is None:
                return None
            for key, value in payload.model_dump(exclude_none=True).items():
                setattr(row, key, value)
            row.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            return publish_item_row_to_contract(row)

    def attempt_detail(self, attempt_id: str) -> PublishAttemptDetail | None:
        with self.session_factory() as session:
            row = session.get(PublishAttemptRow, attempt_id)
            if row is None:
                return None
            item = session.get(PublishBatchItemRow, row.item_id)
            record = None
            if item is not None:
                record_row = session.scalar(
                    select(PublishRecordRow)
                    .where(PublishRecordRow.publish_batch_id == item.batch_id)
                    .where(PublishRecordRow.publish_package_id == item.publish_package_id)
                    .where(PublishRecordRow.platform == item.platform)
                    .order_by(PublishRecordRow.updated_at.desc())
                    .limit(1)
                )
                record = publish_record_row_to_contract(record_row) if record_row else None
            return PublishAttemptDetail(attempt=publish_attempt_row_to_contract(row), record=record)
