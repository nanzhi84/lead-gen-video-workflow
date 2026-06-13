from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from packages.migrations.legacy_asset_utils import (
    DEFAULT_BUCKET,
    DEFAULT_KINDS,
    DEFAULT_UPLOAD_PREFIX,
    IMAGE_EXTENSIONS,
    as_list,
    guess_mime,
    idempotency_key,
    optional_float,
    read_json_file,
    template_kind,
)


@dataclass
class MigrationResult:
    dry_run: bool
    case_rows: list[dict] = field(default_factory=list)
    script_specs: list[dict] = field(default_factory=list)
    script_rows: list[dict] = field(default_factory=list)
    media_rows: list[dict] = field(default_factory=list)
    rows_by_kind: dict[str, list[dict]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    case_id_map: dict[str, str] = field(default_factory=dict)

    @property
    def failed_count(self) -> int:
        return len(self.failures) + sum(int(report.get("failed_count", 0)) for report in self.reports)


class LegacyAssetMigrator:
    def __init__(
        self,
        *,
        oss_client: Any,
        import_client: Any | None,
        bucket: str = DEFAULT_BUCKET,
        upload_prefix: str = DEFAULT_UPLOAD_PREFIX,
    ) -> None:
        self.oss = oss_client
        self.import_client = import_client
        self.bucket = bucket
        self.upload_prefix = upload_prefix.strip("/") + "/"

    def run(
        self,
        *,
        case_meta_dir: Path,
        apply: bool,
        kinds: set[str] | None = None,
        out: TextIO | None = sys.stdout,
    ) -> MigrationResult:
        selected = set(kinds or DEFAULT_KINDS)
        result = MigrationResult(dry_run=not apply)
        cases = read_json_file(case_meta_dir / "cases.json")
        scripts = read_json_file(case_meta_dir / "candidate_scripts.json")
        needs_case_map = bool(selected.intersection({"script", "broll", "portrait", "cover"}))
        if "case" in selected or (apply and needs_case_map):
            result.case_rows = [self._case_row(item) for item in cases]
        if "script" in selected:
            result.script_specs = [item for item in scripts if isinstance(item, dict)]

        self._collect_bgm(result, selected)
        for case in cases:
            if isinstance(case, dict) and case.get("id"):
                self._collect_broll(
                    result,
                    str(case["id"]),
                    str(case.get("name") or case.get("case_name") or case["id"]),
                    selected,
                )
        self._collect_templates(result, selected, kinds is None)
        self._collect_fonts(result, selected)
        self._collect_covers(result, selected)

        if not apply:
            self._print_summary(result, out)
            return result
        if self.import_client is None:
            raise ValueError("import_client is required when apply=True.")
        if result.case_rows:
            report = self._post("case", result.case_rows, result)
            self._record_case_mapping(report, result.case_rows, result)
        if result.script_specs:
            result.script_rows = self._script_rows(result.script_specs, result.case_id_map, result)
            if result.script_rows:
                self._post("script", result.script_rows, result)
        result.media_rows = self._finalize_media_rows(result.media_rows, result.case_id_map, result)
        if result.media_rows:
            self._post("media", result.media_rows, result)
        self._print_summary(result, out)
        return result

    def _case_row(self, item: dict) -> dict:
        product = item.get("product") or item.get("product_name")
        row = {
            "external_id": str(item.get("id")),
            "name": str(item.get("name") or item.get("case_name") or item.get("id")),
            "industry": item.get("industry"),
            "product": product,
            "product_name": item.get("product_name") or product,
            "target_audience": item.get("target_audience"),
            "key_selling_points": item.get("key_selling_points") or [],
            "ip_persona": item.get("ip_persona"),
            "description": item.get("description") or "",
        }
        return {key: value for key, value in row.items() if value is not None}

    def _script_rows(self, scripts: list[dict], case_id_map: dict[str, str], result: MigrationResult) -> list[dict]:
        rows = []
        for item in scripts:
            legacy_case_id = str(item.get("case_id") or "")
            case_id = case_id_map.get(legacy_case_id)
            if not case_id:
                result.failures.append(f"script {item.get('id')} has no mapped case_id for {legacy_case_id}")
                continue
            title_parts = [str(item.get("case_name") or "").strip(), str(item.get("scene_type") or "").strip()]
            rows.append(
                {
                    "external_id": str(item.get("id")),
                    "case_id": case_id,
                    "title": " ".join(part for part in title_parts if part) or str(item.get("id") or "Imported script"),
                    "script": str(item.get("content") or item.get("script") or ""),
                    "tags": item.get("tags") or [],
                }
            )
        return rows

    def _collect_bgm(self, result: MigrationResult, selected: set[str]) -> None:
        if "bgm" not in selected:
            return
        data = self._load_oss_json(f"{self.upload_prefix}bgm_library/library.json", result)
        for item in as_list(data.get("tracks") if isinstance(data, dict) else data):
            row = self._media_row(
                item, kind="bgm", group="bgm", path=item.get("path") or item.get("filename"),
                title=item.get("name") or item.get("filename") or item.get("id"),
                external_id=item.get("id") or item.get("filename"), duration=item.get("duration"),
                legacy_case_id=None, result=result,
            )
            self._add_media_row(result, "bgm", row)

    def _collect_broll(
        self,
        result: MigrationResult,
        legacy_case_id: str,
        legacy_case_name: str,
        selected: set[str],
    ) -> None:
        if "broll" not in selected:
            return
        case_dir = f"{legacy_case_name.strip()}_{legacy_case_id[:8]}"
        data = self._load_oss_json(f"{self.upload_prefix}cases/{case_dir}/broll/library.json", result)
        for item in as_list(data.get("videos") if isinstance(data, dict) else data):
            row = self._media_row(
                item, kind="broll", group="broll", path=item.get("path") or item.get("filename"),
                title=item.get("scene") or item.get("name") or item.get("filename") or item.get("id"),
                external_id=item.get("id") or item.get("filename"), duration=item.get("duration"),
                legacy_case_id=legacy_case_id, result=result,
            )
            self._add_media_row(result, "broll", row)

    def _collect_templates(self, result: MigrationResult, selected: set[str], include_extra: bool) -> None:
        if not include_extra and not selected.intersection({"portrait", "bgm", "broll"}):
            return
        data = self._load_oss_json(f"{self.upload_prefix}templates_pool/index.json", result)
        values = data.values() if isinstance(data, dict) else as_list(data)
        for item in values:
            if not isinstance(item, dict):
                continue
            kind = template_kind(item)
            if kind not in selected and not (include_extra and kind not in DEFAULT_KINDS):
                continue
            row = self._media_row(
                item, kind=kind, group=kind, path=item.get("path"),
                title=item.get("name") or item.get("filename") or item.get("id"),
                external_id=item.get("id"), duration=item.get("duration"),
                legacy_case_id=item.get("case_id"), result=result,
            )
            self._add_media_row(result, kind, row)

    def _collect_fonts(self, result: MigrationResult, selected: set[str]) -> None:
        if "font" not in selected:
            return
        return

    def _collect_covers(self, result: MigrationResult, selected: set[str]) -> None:
        if "cover" not in selected:
            return
        for key in self.oss.list_keys(f"{self.upload_prefix}cover_templates/"):
            if Path(key).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            rel = key.removeprefix(self.upload_prefix)
            legacy_case_id = rel.split("/")[1] if len(rel.split("/")) >= 3 else None
            row = self._media_row(
                {"path": key}, kind="cover_template", group="cover", path=key,
                title=Path(key).stem, external_id=f"cover:{legacy_case_id}:{Path(key).name}",
                duration=None, legacy_case_id=legacy_case_id, result=result,
            )
            self._add_media_row(result, "cover", row)

    def _media_row(
        self,
        item: dict,
        *,
        kind: str,
        group: str,
        path: Any,
        title: Any,
        external_id: Any,
        duration: Any,
        legacy_case_id: Any,
        result: MigrationResult,
    ) -> dict | None:
        key = self._oss_key(path)
        if not key:
            result.warnings.append(f"WARN cannot build OSS key for {group}:{external_id}")
            return None
        if not self.oss.object_exists(key):
            result.warnings.append(f"WARN missing OSS key: {key} ({group}:{external_id})")
            return None
        row = {
            "case_id": None,
            "_legacy_case_id": str(legacy_case_id) if legacy_case_id else None,
            "kind": kind,
            "title": str(title or Path(key).stem),
            "uri": f"s3://{self.bucket}/{key}",
            "mime": guess_mime(key),
            "external_id": str(external_id or Path(key).name),
        }
        duration_sec = optional_float(duration)
        if duration_sec is not None:
            row["duration_sec"] = duration_sec
        for field_name in ("sha256", "width", "height"):
            if item.get(field_name) is not None:
                row[field_name] = item[field_name]
        return row

    def _add_media_row(self, result: MigrationResult, group: str, row: dict | None) -> None:
        if row:
            result.media_rows.append(row)
            result.rows_by_kind.setdefault(group, []).append(row)

    def _finalize_media_rows(self, rows: list[dict], case_id_map: dict[str, str], result: MigrationResult) -> list[dict]:
        finalized = []
        for row in rows:
            legacy_case_id = row.pop("_legacy_case_id", None)
            if legacy_case_id:
                mapped = case_id_map.get(legacy_case_id)
                if not mapped:
                    message = f"media {row.get('external_id')} has no mapped case_id for {legacy_case_id}"
                    if row.get("kind") == "portrait":
                        result.warnings.append(f"WARN {message}; skipped")
                    else:
                        result.failures.append(message)
                    continue
                row["case_id"] = mapped
            finalized.append(row)
        return finalized

    def _load_oss_json(self, key: str, result: MigrationResult) -> Any:
        try:
            return self.oss.get_json(key)
        except FileNotFoundError:
            result.warnings.append(f"WARN missing OSS index: {key}")
            return {}

    def _oss_key(self, path: Any) -> str | None:
        if path is None:
            return None
        text = str(path).strip().lstrip("/")
        if not text:
            return None
        if text.startswith("s3://"):
            return urlsplit(text).path.lstrip("/") or None
        if text.startswith(self.upload_prefix):
            return text
        while text.startswith("uploads/"):
            text = text.removeprefix("uploads/")
        return f"{self.upload_prefix}{text}" if text else None

    def _key_from_uri(self, uri: str) -> str:
        return urlsplit(uri).path.lstrip("/")

    def _post(self, import_type: str, rows: list[dict], result: MigrationResult) -> dict:
        clean_rows = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
        report = self.import_client.import_batch(
            import_type, clean_rows, idempotency_key=idempotency_key(import_type, clean_rows)
        )
        result.reports.append(report)
        for item in report.get("results", []):
            if item.get("status") == "failed":
                result.failures.append(f"{import_type} row {item.get('row_index')} failed: {item.get('error')}")
        return report

    def _record_case_mapping(self, report: dict, rows: list[dict], result: MigrationResult) -> None:
        for item in report.get("results", []):
            index = int(item.get("row_index", -1))
            if index < 0 or index >= len(rows):
                continue
            internal_id = item.get("internal_id")
            external_id = rows[index].get("external_id")
            if internal_id:
                result.case_id_map[str(external_id)] = str(internal_id)
            else:
                result.failures.append(f"case {external_id} import returned no internal_id")

    def _print_summary(self, result: MigrationResult, out: TextIO | None) -> None:
        if out is None:
            return
        mode = "DRY-RUN" if result.dry_run else "APPLY"
        print(f"{mode} legacy asset migration", file=out)
        print(f"case rows: {len(result.case_rows)}", file=out)
        print(f"script rows: {len(result.script_specs if result.dry_run else result.script_rows)}", file=out)
        for kind, rows in sorted(result.rows_by_kind.items()):
            print(f"{kind} media rows: {len(rows)}", file=out)
            if rows:
                print(f"{kind} sample uri: {rows[0]['uri']}", file=out)
        print(f"warnings: {len(result.warnings)}", file=out)
        for warning in result.warnings:
            print(warning, file=out)
        print(f"failures: {result.failed_count}", file=out)
        for failure in result.failures:
            print(f"ERROR {failure}", file=out)


def run_migration(
    *,
    case_meta_dir: Path,
    oss_client: Any,
    import_client: Any | None,
    apply: bool,
    kinds: set[str] | None = None,
    bucket: str = DEFAULT_BUCKET,
    upload_prefix: str = DEFAULT_UPLOAD_PREFIX,
    out: TextIO | None = sys.stdout,
) -> MigrationResult:
    return LegacyAssetMigrator(
        oss_client=oss_client,
        import_client=import_client,
        bucket=bucket,
        upload_prefix=upload_prefix,
    ).run(case_meta_dir=case_meta_dir, apply=apply, kinds=kinds, out=out)
