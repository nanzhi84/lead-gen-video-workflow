from __future__ import annotations

from packages.migrations.legacy_assets import LegacyAssetMigrator, MigrationResult


class FakeOss:
    def __init__(self, payload: object, existing_keys: set[str]):
        self.payload = payload
        self.existing_keys = existing_keys
        self.checked: list[str] = []

    def get_json(self, key: str):
        return self.payload

    def object_exists(self, key: str) -> bool:
        self.checked.append(key)
        return key in self.existing_keys


def _collect(payload: object) -> MigrationResult:
    prefix = "digital-human-platform/dev/uploads/"
    migrator = LegacyAssetMigrator(
        oss_client=FakeOss(payload, {f"{prefix}video_templates/x.mp4"}),
        import_client=None,
        upload_prefix=prefix,
    )
    result = MigrationResult(dry_run=False, case_id_map={"legacy-case": "genesis-case"})

    migrator._collect_templates(result, {"portrait"}, include_extra=False)
    result.media_rows = migrator._finalize_media_rows(result.media_rows, result.case_id_map, result)

    return result


def test_collect_templates_reads_real_templates_wrapper_as_portrait_media():
    result = _collect(
        {
            "templates": [
                {
                    "id": "tpl-real",
                    "material_type": "portrait",
                    "path": "video_templates/x.mp4",
                    "case_id": "legacy-case",
                }
            ]
        }
    )

    assert result.warnings == []
    assert result.media_rows == [
        {
            "case_id": "genesis-case",
            "kind": "portrait",
            "title": "tpl-real",
            "uri": "s3://videoretalk-test-bucket/digital-human-platform/dev/uploads/video_templates/x.mp4",
            "mime": "video/mp4",
            "external_id": "tpl-real",
        }
    ]


def test_collect_templates_keeps_dict_of_items_fallback():
    result = _collect(
        {
            "tpl-fallback": {
                "id": "tpl-fallback",
                "material_type": "portrait",
                "path": "video_templates/x.mp4",
                "case_id": "legacy-case",
            }
        }
    )

    assert result.warnings == []
    assert result.media_rows[0]["kind"] == "portrait"
    assert "video_templates/x.mp4" in result.media_rows[0]["uri"]
