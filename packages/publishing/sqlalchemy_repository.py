from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import (
    ArtifactKind,
    ArtifactRef,
    CreatePublishBatchRequest,
    CreatePublishPackageRequest,
    ErrorCode,
    PatchPublishItemRequest,
    ProviderError,
    PublishAttempt,
    PublishAttemptDetail,
    PublishBatchItemVm,
    PublishBatchVm,
    PublishDefaults,
    PublishPackage,
    PublishRecord,
    SubmitPublishBatchRequest,
    utcnow,
)
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


def artifact_ref_from_row(row: ArtifactRow) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=row.id,
        kind=ArtifactKind(row.kind),
        schema_version=row.schema_version,
        sha256=row.sha256,
    )


def publish_package_row_to_contract(row: PublishPackageRow) -> PublishPackage:
    return PublishPackage(
        id=row.id,
        case_id=row.case_id,
        source_finished_video_id=row.source_finished_video_id,
        upload_artifact_id=row.upload_artifact_id,
        video_artifact=ArtifactRef.model_validate(row.video_artifact),
        cover_artifact=ArtifactRef.model_validate(row.cover_artifact) if row.cover_artifact else None,
        platform_defaults=PublishDefaults.model_validate(row.platform_defaults),
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def publish_item_row_to_contract(row: PublishBatchItemRow) -> PublishBatchItemVm:
    return PublishBatchItemVm(
        id=row.id,
        publish_package_id=row.publish_package_id,
        platform=row.platform,
        title=row.title,
        description=row.description,
        selected=row.selected,
        status=row.status,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def publish_batch_row_to_contract(session: Session, row: PublishBatchRow) -> PublishBatchVm:
    statement = (
        select(PublishBatchItemRow)
        .where(PublishBatchItemRow.batch_id == row.id)
        .order_by(PublishBatchItemRow.created_at.asc(), PublishBatchItemRow.id.asc())
    )
    items = [publish_item_row_to_contract(item) for item in session.scalars(statement)]
    return PublishBatchVm(
        id=row.id,
        status=row.status,
        items=items,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def publish_attempt_row_to_contract(row: PublishAttemptRow) -> PublishAttempt:
    return PublishAttempt(
        id=row.id,
        item_id=row.item_id,
        platform=row.platform,
        status=row.status,
        error=ProviderError.model_validate(row.error) if row.error else None,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def publish_record_row_to_contract(row: PublishRecordRow) -> PublishRecord:
    return PublishRecord(
        id=row.id,
        case_id=row.case_id,
        video_version_id=row.video_version_id,
        publish_package_id=row.publish_package_id,
        publish_batch_id=row.publish_batch_id,
        platform=row.platform,
        status=row.status,
        cover_artifact_id=row.cover_artifact_id,
        published_at=row.published_at,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
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

    def list_batches(self, *, limit: int = 50) -> list[PublishBatchVm]:
        with self.session_factory() as session:
            statement = select(PublishBatchRow).order_by(PublishBatchRow.updated_at.desc()).limit(limit)
            rows = list(session.scalars(statement))
            return [publish_batch_row_to_contract(session, row) for row in rows]

    def get_batch(self, batch_id: str) -> PublishBatchVm | None:
        with self.session_factory() as session:
            row = session.get(PublishBatchRow, batch_id)
            return publish_batch_row_to_contract(session, row) if row else None

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
                            status="draft",
                        )
                    )
            session.commit()
            session.refresh(batch)
            return publish_batch_row_to_contract(session, batch)

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

            item_status = "submitted" if payload.dry_run else "published"
            batch.status = item_status
            batch.updated_at = utcnow()
            for item in selected_items:
                item.status = item_status
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
                            status=item_status,
                            cover_artifact_id=cover_ref.artifact_id if cover_ref else None,
                            published_at=utcnow() if item_status == "published" else None,
                        )
                    )
                session.add(
                    PublishAttemptRow(
                        id=new_id("pub_attempt"),
                        item_id=item.id,
                        platform=item.platform,
                        status="succeeded",
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
