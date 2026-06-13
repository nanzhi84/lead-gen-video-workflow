from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any


DEFAULT_BUCKET = "videoretalk-test-bucket"
DEFAULT_UPLOAD_PREFIX = "digital-human-platform/dev/uploads/"
DEFAULT_KINDS = {"case", "script", "bgm", "broll", "portrait", "font", "cover"}
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".ttc"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_kinds(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    parsed = {item.strip() for value in values for item in value.split(",") if item.strip()}
    invalid = parsed - DEFAULT_KINDS
    if invalid:
        raise SystemExit(f"Unsupported --kinds values: {', '.join(sorted(invalid))}")
    return parsed


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def map_legacy_cases_by_name(
    legacy_cases: Any,
    existing_cases: Any,
    *,
    warn_missing: bool,
) -> tuple[dict[str, str], set[str], list[str]]:
    by_name: dict[str, str] = {}
    duplicate_names: set[str] = set()
    for item in as_list(existing_cases):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        case_id = item.get("id")
        if not name or not case_id:
            continue
        if name in by_name:
            duplicate_names.add(name)
        else:
            by_name[name] = str(case_id)
    for name in duplicate_names:
        by_name.pop(name, None)

    mapped: dict[str, str] = {}
    blocked: set[str] = set()
    warnings: list[str] = []
    for item in as_list(legacy_cases):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        legacy_id = str(item["id"])
        name = str(item.get("name") or item.get("case_name") or item["id"]).strip()
        if name in duplicate_names:
            warnings.append(f"WARN multiple existing genesis cases named {name} for legacy case {legacy_id}")
            blocked.add(legacy_id)
            continue
        case_id = by_name.get(name)
        if case_id:
            mapped[legacy_id] = case_id
        elif warn_missing:
            warnings.append(f"WARN no existing genesis case named {name} for legacy case {legacy_id}")
    return mapped, blocked, warnings


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def guess_mime(key: str) -> str:
    suffix = Path(key).suffix.lower()
    if suffix in FONT_EXTENSIONS:
        return {
            ".ttf": "font/ttf",
            ".otf": "font/otf",
            ".woff": "font/woff",
            ".woff2": "font/woff2",
            ".ttc": "font/collection",
        }[suffix]
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def template_kind(item: dict) -> str:
    material_type = str(item.get("material_type") or item.get("kind") or "").strip().lower()
    if material_type == "portrait":
        return "portrait"
    if material_type in {"bgm", "broll", "font"}:
        return material_type
    suffix = Path(str(item.get("path") or "")).suffix.lower()
    return "video" if suffix in {".mp4", ".mov", ".m4v", ".webm"} else "other"


def idempotency_key(import_type: str, rows: list[dict]) -> str:
    payload = json.dumps({"import_type": import_type, "rows": rows}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"m6vb-legacy-assets-{import_type}-{digest}"


def is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {}) if isinstance(response.get("Error"), dict) else {}
        code = str(error.get("Code"))
        status = response.get("ResponseMetadata", {})
        return code in {"404", "NoSuchBucket", "NoSuchKey", "NotFound"} or (
            isinstance(status, dict) and status.get("HTTPStatusCode") == 404
        )
    return False
