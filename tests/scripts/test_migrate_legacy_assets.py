from __future__ import annotations

import json
from pathlib import Path

from scripts import migrate_legacy_assets as migrate


class FakeOss:
    def __init__(self, json_by_key: dict[str, object], existing_keys: set[str], listed: list[str] | None = None):
        self.json_by_key = json_by_key
        self.existing_keys = existing_keys
        self.listed = listed or []
        self.checked: list[str] = []

    def get_json(self, key: str):
        if key not in self.json_by_key:
            raise FileNotFoundError(key)
        return self.json_by_key[key]

    def list_keys(self, prefix: str) -> list[str]:
        return [key for key in self.listed if key.startswith(prefix)]

    def object_exists(self, key: str) -> bool:
        self.checked.append(key)
        return key in self.existing_keys


class FakeImportApi:
    def __init__(self):
        self.calls: list[tuple[str, list[dict], str | None]] = []

    def import_batch(self, import_type: str, rows: list[dict], *, idempotency_key: str | None = None):
        self.calls.append((import_type, rows, idempotency_key))
        return {
            "status": "completed",
            "created_count": len(rows),
            "skipped_count": 0,
            "failed_count": 0,
            "results": [
                {
                    "row_index": index,
                    "status": "created",
                    "external_id": row.get("external_id"),
                    "internal_id": f"gen_{import_type}_{index}",
                }
                for index, row in enumerate(rows)
            ],
        }


def _write_case_meta(root: Path) -> None:
    (root / "cases.json").write_text(
        json.dumps(
            [
                {
                    "id": "case-1",
                    "name": "Case One",
                    "industry": "auto",
                    "target_audience": "drivers",
                    "key_selling_points": ["fast"],
                    "ip_persona": "expert",
                    "product_name": "Spray",
                    "description": "Legacy case",
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "candidate_scripts.json").write_text(
        json.dumps(
            [
                {
                    "id": "script-1",
                    "content": "script body",
                    "case_id": "case-1",
                    "case_name": "Case One",
                    "scene_type": "hook",
                    "tags": ["tag-a"],
                }
            ]
        ),
        encoding="utf-8",
    )


def _oss_payload(prefix: str):
    return {
        f"{prefix}bgm_library/library.json": {
            "tracks": [
                {
                    "id": "bgm-1",
                    "name": "BGM One",
                    "path": "uploads/bgm_library/bgm.mp3",
                    "duration": 3.5,
                }
            ]
        },
        f"{prefix}cases/case-1/broll/library.json": {
            "videos": [
                {
                    "id": "broll-1",
                    "filename": "clip.mp4",
                    "path": "cases/case-1/broll/videos/clip.mp4",
                    "scene": "factory",
                    "duration": 8,
                }
            ]
        },
        f"{prefix}templates_pool/index.json": {
            "tpl-1": {
                "id": "tpl-1",
                "name": "Portrait One",
                "path": "video_templates/portrait.mp4",
                "material_type": "portrait",
                "duration": 12,
                "case_id": "case-1",
            }
        },
        f"{prefix}fonts/font_annotations.json": [
            {"id": "font-1", "name": "Font One", "path": "fonts/user/font.ttf"}
        ],
    }


def test_apply_imports_cases_first_and_maps_legacy_case_ids_into_script_and_media(tmp_path):
    _write_case_meta(tmp_path)
    prefix = "digital-human-platform/dev/uploads/"
    keys = {
        f"{prefix}bgm_library/bgm.mp3",
        f"{prefix}cases/case-1/broll/videos/clip.mp4",
        f"{prefix}video_templates/portrait.mp4",
        f"{prefix}fonts/user/font.ttf",
        f"{prefix}cover_templates/case-1/cover.png",
    }
    oss = FakeOss(
        _oss_payload(prefix),
        keys,
        listed=[f"{prefix}cover_templates/case-1/cover.png"],
    )
    api = FakeImportApi()

    result = migrate.run_migration(
        case_meta_dir=tmp_path,
        oss_client=oss,
        import_client=api,
        apply=True,
        out=None,
    )

    assert result.failed_count == 0
    assert [call[0] for call in api.calls] == ["case", "script", "media"]
    case_rows = api.calls[0][1]
    assert case_rows == [
        {
            "external_id": "case-1",
            "name": "Case One",
            "industry": "auto",
            "product": "Spray",
            "product_name": "Spray",
            "target_audience": "drivers",
            "key_selling_points": ["fast"],
            "ip_persona": "expert",
            "description": "Legacy case",
        }
    ]
    assert api.calls[1][1][0]["case_id"] == "gen_case_0"
    assert api.calls[1][1][0]["external_id"] == "script-1"
    media_rows = api.calls[2][1]
    assert {row["kind"] for row in media_rows} == {"bgm", "broll", "portrait", "font", "cover_template"}
    assert {row["uri"] for row in media_rows} == {
        f"s3://videoretalk-test-bucket/{prefix}bgm_library/bgm.mp3",
        f"s3://videoretalk-test-bucket/{prefix}cases/case-1/broll/videos/clip.mp4",
        f"s3://videoretalk-test-bucket/{prefix}video_templates/portrait.mp4",
        f"s3://videoretalk-test-bucket/{prefix}fonts/user/font.ttf",
        f"s3://videoretalk-test-bucket/{prefix}cover_templates/case-1/cover.png",
    }
    assert next(row for row in media_rows if row["kind"] == "bgm")["case_id"] is None
    assert next(row for row in media_rows if row["kind"] == "broll")["case_id"] == "gen_case_0"
    assert next(row for row in media_rows if row["kind"] == "portrait")["case_id"] == "gen_case_0"
    assert next(row for row in media_rows if row["kind"] == "cover_template")["case_id"] == "gen_case_0"


def test_missing_oss_key_is_skipped_and_reported_as_warning(tmp_path):
    _write_case_meta(tmp_path)
    prefix = "digital-human-platform/dev/uploads/"
    oss = FakeOss(_oss_payload(prefix), {f"{prefix}bgm_library/bgm.mp3"})
    result = migrate.run_migration(
        case_meta_dir=tmp_path,
        oss_client=oss,
        import_client=FakeImportApi(),
        apply=False,
        out=None,
    )

    assert "bgm" in result.rows_by_kind
    assert [row["kind"] for row in result.media_rows] == ["bgm"]
    assert any("WARN missing OSS key" in warning for warning in result.warnings)
    assert f"{prefix}cases/case-1/broll/videos/clip.mp4" in oss.checked


def test_dry_run_does_not_call_import_api(tmp_path):
    _write_case_meta(tmp_path)
    prefix = "digital-human-platform/dev/uploads/"
    oss = FakeOss(_oss_payload(prefix), {f"{prefix}bgm_library/bgm.mp3"})
    api = FakeImportApi()

    result = migrate.run_migration(
        case_meta_dir=tmp_path,
        oss_client=oss,
        import_client=api,
        apply=False,
        kinds={"case", "script", "bgm"},
        out=None,
    )

    assert result.dry_run is True
    assert api.calls == []
    assert len(result.case_rows) == 1
    assert len(result.script_specs) == 1
    assert [row["kind"] for row in result.media_rows] == ["bgm"]
