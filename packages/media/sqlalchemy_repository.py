from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.core.contracts import (
    AnnotationEditorVm,
    AnnotationRunResponse,
    ArtifactRef,
    ArtifactKind,
    CloneVoiceRequest,
    CreateMediaAssetFromUploadRequest,
    DesignVoiceRequest,
    ErrorCode,
    MediaAssetCard,
    MediaAssetDetail,
    MediaAssetRecord,
    PatchAnnotationRequest,
    PatchVoiceRequest,
    RerunAnnotationRequest,
    VoicePreviewRequest,
    VoicePreviewResponse,
    VoiceProfile,
    utcnow,
)
from packages.core.storage.database import AnnotationRow, ArtifactRow, MediaAssetRow, UploadSessionRow, VoiceProfileRow
from packages.core.storage.repository import new_id
from packages.core.workflow import NodeExecutionError


def media_asset_row_to_contract(row: MediaAssetRow) -> MediaAssetRecord:
    return MediaAssetRecord(
        id=row.id,
        case_id=row.case_id,
        title=row.title,
        kind=row.kind,
        source_artifact_id=row.source_artifact_id,
        tags=list(row.tags or []),
        annotation_status=row.annotation_status,
        usable=row.usable,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def annotation_row_to_editor(row: AnnotationRow, asset: MediaAssetRow) -> AnnotationEditorVm:
    return AnnotationEditorVm(
        asset=media_asset_row_to_contract(asset),
        etag=row.etag,
        canonical=row.canonical,
        projection=row.projection,
        editable_paths=list(row.editable_paths or []),
    )


def voice_row_to_contract(row: VoiceProfileRow) -> VoiceProfile:
    return VoiceProfile(
        id=row.id,
        display_name=row.display_name,
        source=row.source,
        provider_profile_id=row.provider_profile_id,
        preview_artifact_id=row.preview_artifact_id,
        enabled=row.enabled,
        schema_version=row.schema_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def artifact_ref_from_row(row: ArtifactRow) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=row.id,
        kind=ArtifactKind(row.kind),
        schema_version=row.schema_version,
        sha256=row.sha256,
    )


def _set_json_pointer(target: dict, path_parts: list[str], value) -> None:
    current = target
    for part in path_parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    if path_parts:
        current[path_parts[-1]] = value


def _apply_annotation_operations(canonical: dict, projection: dict, operations: list[dict]) -> None:
    for operation in operations:
        op_name = operation.get("op", "replace")
        path = operation.get("path")
        if op_name not in {"add", "replace"} or not isinstance(path, str) or "value" not in operation:
            continue
        value = operation["value"]
        if path == "/labels":
            canonical["labels"] = value
        elif path == "/usable":
            projection["usable"] = value
        elif path == "/title":
            projection["title"] = value
        elif path.startswith("/canonical/"):
            _set_json_pointer(canonical, [part for part in path.removeprefix("/canonical/").split("/") if part], value)
        elif path.startswith("/projection/"):
            _set_json_pointer(projection, [part for part in path.removeprefix("/projection/").split("/") if part], value)


class SqlAlchemyMediaRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def list_assets(
        self,
        *,
        limit: int = 50,
        case_id: str | None = None,
        kind: str | None = None,
        annotation_status: str | None = None,
    ) -> list[MediaAssetCard]:
        with self.session_factory() as session:
            statement = select(MediaAssetRow)
            if case_id:
                statement = statement.where(MediaAssetRow.case_id == case_id)
            if kind:
                statement = statement.where(MediaAssetRow.kind == kind)
            if annotation_status:
                statement = statement.where(MediaAssetRow.annotation_status == annotation_status)
            statement = statement.order_by(MediaAssetRow.updated_at.desc()).limit(limit)
            return [
                MediaAssetCard(asset=media_asset_row_to_contract(row), preview_url=f"local://media/{row.id}")
                for row in session.scalars(statement)
            ]

    def get_asset_detail(self, asset_id: str) -> MediaAssetDetail | None:
        with self.session_factory() as session:
            row = session.get(MediaAssetRow, asset_id)
            if row is None:
                return None
            return MediaAssetDetail(
                asset=media_asset_row_to_contract(row),
                preview_url=f"local://media/{row.id}",
            )

    def create_asset_from_upload(self, payload: CreateMediaAssetFromUploadRequest) -> MediaAssetRecord:
        with self.session_factory() as session:
            upload = session.get(UploadSessionRow, payload.upload_session_id)
            if upload is None or upload.status != "completed":
                raise NodeExecutionError(ErrorCode.upload_invalid_state, "Upload must be completed first.")
            artifact = session.scalar(
                select(ArtifactRow)
                .where(ArtifactRow.kind == ArtifactKind.uploaded_file.value)
                .where(ArtifactRow.payload.contains({"id": upload.id}))
                .order_by(ArtifactRow.created_at.desc())
                .limit(1)
            )
            if artifact is None:
                raise NodeExecutionError(ErrorCode.artifact_missing, "Completed upload artifact is missing.")
            row = MediaAssetRow(
                id=new_id("asset"),
                case_id=payload.case_id,
                title=payload.title,
                kind=payload.kind,
                source_artifact_id=artifact.id,
                tags=payload.tags,
                annotation_status="pending",
                usable=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return media_asset_row_to_contract(row)

    def artifact_uri_for_asset(self, asset_id: str) -> str | None:
        with self.session_factory() as session:
            asset = session.get(MediaAssetRow, asset_id)
            if asset is None:
                return None
            if not asset.source_artifact_id:
                return ""
            artifact = session.get(ArtifactRow, asset.source_artifact_id)
            return artifact.uri if artifact is not None else ""

    def get_or_create_annotation(self, asset_id: str) -> AnnotationEditorVm | None:
        with self.session_factory() as session:
            asset = session.get(MediaAssetRow, asset_id)
            if asset is None:
                return None
            row = self._annotation_row(session, asset_id)
            if row is None:
                row = AnnotationRow(
                    id=new_id("ann"),
                    asset_id=asset_id,
                    etag=new_id("etag"),
                    canonical_schema="MediaAnnotationCanonical.v1",
                    canonical={"labels": list(asset.tags or []), "kind": asset.kind},
                    projection_schema="MediaAnnotationProjection.v1",
                    projection={"title": asset.title, "usable": asset.usable},
                    editable_paths=["/labels", "/usable", "/title"],
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                session.refresh(asset)
            return annotation_row_to_editor(row, asset)

    def patch_annotation(self, asset_id: str, payload: PatchAnnotationRequest) -> AnnotationEditorVm | None:
        with self.session_factory() as session:
            asset = session.get(MediaAssetRow, asset_id)
            if asset is None:
                return None
            row = self._annotation_row(session, asset_id)
            if row is None:
                row = AnnotationRow(
                    id=new_id("ann"),
                    asset_id=asset_id,
                    etag=new_id("etag"),
                    canonical_schema="MediaAnnotationCanonical.v1",
                    canonical={"labels": list(asset.tags or []), "kind": asset.kind},
                    projection_schema="MediaAnnotationProjection.v1",
                    projection={"title": asset.title, "usable": asset.usable},
                    editable_paths=["/labels", "/usable", "/title"],
                )
                session.add(row)
                session.flush()
            canonical = dict(row.canonical or {})
            projection = dict(row.projection or {})
            _apply_annotation_operations(canonical, projection, payload.patch.operations)
            row.canonical = canonical
            row.projection = projection
            row.etag = new_id("etag")
            row.updated_at = utcnow()
            asset.annotation_status = "annotated"
            asset.updated_at = utcnow()
            session.commit()
            session.refresh(row)
            session.refresh(asset)
            return annotation_row_to_editor(row, asset)

    def rerun_annotation(self, asset_id: str, payload: RerunAnnotationRequest) -> AnnotationRunResponse | None:
        with self.session_factory() as session:
            asset = session.get(MediaAssetRow, asset_id)
            if asset is None:
                return None
            row = self._annotation_row(session, asset_id)
            if row is None:
                row = AnnotationRow(
                    id=new_id("ann"),
                    asset_id=asset_id,
                    etag=new_id("etag"),
                    canonical_schema="MediaAnnotationCanonical.v1",
                    canonical={"labels": list(asset.tags or []), "kind": asset.kind},
                    projection_schema="MediaAnnotationProjection.v1",
                    projection={"title": asset.title, "usable": asset.usable},
                    editable_paths=["/labels", "/usable", "/title"],
                )
                session.add(row)
            asset.annotation_status = "annotated"
            asset.updated_at = utcnow()
            session.commit()
            return AnnotationRunResponse(asset_id=asset_id, run_id=None, status="completed")

    def _annotation_row(self, session: Session, asset_id: str) -> AnnotationRow | None:
        return session.scalar(
            select(AnnotationRow)
            .where(AnnotationRow.asset_id == asset_id)
            .order_by(AnnotationRow.updated_at.desc())
            .limit(1)
        )

    def list_voices(
        self,
        *,
        source: str | None = None,
        enabled: bool | None = None,
        limit: int = 50,
    ) -> list[VoiceProfile]:
        with self.session_factory() as session:
            statement = select(VoiceProfileRow)
            if source:
                statement = statement.where(VoiceProfileRow.source == source)
            if enabled is not None:
                statement = statement.where(VoiceProfileRow.enabled == enabled)
            statement = statement.order_by(VoiceProfileRow.updated_at.desc()).limit(limit)
            return [voice_row_to_contract(row) for row in session.scalars(statement)]

    def clone_voice(self, payload: CloneVoiceRequest) -> VoiceProfile:
        with self.session_factory() as session:
            upload = session.get(UploadSessionRow, payload.reference_upload_session_id)
            if upload is None or upload.status != "completed":
                raise NodeExecutionError(ErrorCode.upload_invalid_state, "Reference upload must be completed first.")
            row = VoiceProfileRow(
                id=new_id("voice"),
                display_name=payload.display_name,
                source="cloned",
                provider_profile_id=payload.provider_profile_id or "sandbox.tts.default",
                enabled=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return voice_row_to_contract(row)

    def design_voice(self, payload: DesignVoiceRequest) -> VoiceProfile:
        with self.session_factory() as session:
            row = VoiceProfileRow(
                id=new_id("voice"),
                display_name=payload.display_name,
                source="designed",
                provider_profile_id=payload.provider_profile_id or "sandbox.tts.default",
                enabled=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return voice_row_to_contract(row)

    def preview_voice(self, voice_id: str, payload: VoicePreviewRequest) -> VoicePreviewResponse | None:
        with self.session_factory() as session:
            voice = session.get(VoiceProfileRow, voice_id)
            if voice is None:
                return None
            artifact = ArtifactRow(
                id=new_id("art"),
                kind=ArtifactKind.audio_tts.value,
                uri=f"sandbox://voice-preview/{voice_id}.wav",
                payload_schema="VoicePreviewArtifact.v1",
                payload={
                    "voice_id": voice_id,
                    "text": payload.text,
                    "provider_profile_id": payload.provider_profile_id,
                },
            )
            session.add(artifact)
            session.flush()
            voice.preview_artifact_id = artifact.id
            voice.updated_at = utcnow()
            session.commit()
            session.refresh(artifact)
            return VoicePreviewResponse(
                voice_id=voice_id,
                audio_artifact=artifact_ref_from_row(artifact),
                duration_sec=max(1, len(payload.text) / 6),
            )

    def patch_voice(self, voice_id: str, payload: PatchVoiceRequest) -> VoiceProfile | None:
        with self.session_factory() as session:
            voice = session.get(VoiceProfileRow, voice_id)
            if voice is None:
                return None
            for key, value in payload.model_dump(exclude_none=True).items():
                setattr(voice, key, value)
            voice.updated_at = utcnow()
            session.commit()
            session.refresh(voice)
            return voice_row_to_contract(voice)

    def delete_voice(self, voice_id: str) -> None:
        with self.session_factory() as session:
            voice = session.get(VoiceProfileRow, voice_id)
            if voice is not None:
                session.delete(voice)
                session.commit()
