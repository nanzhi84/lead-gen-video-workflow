"""Unit tests for the generic Row -> contract mapping helper."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from packages.core.contracts import Client
from packages.core.storage.row_mapper import map_row


class _Demo(BaseModel):
    id: str
    count: int
    label: str = "default"


def test_map_row_copies_same_named_fields_and_ignores_extras():
    row = SimpleNamespace(id="x", count=3, label="row-label", extra="ignored")
    assert map_row(row, _Demo) == _Demo(id="x", count=3, label="row-label")


def test_map_row_override_takes_precedence_over_row():
    row = SimpleNamespace(id="x", count=3, label="row-label")
    out = map_row(row, _Demo, label="overridden", count=99)
    assert (out.id, out.count, out.label) == ("x", 99, "overridden")


def test_map_row_override_supplies_field_absent_on_row():
    row = SimpleNamespace(id="x", count=3)  # no 'label' attribute
    assert map_row(row, _Demo, label="from-override").label == "from-override"


def test_map_row_optional_field_absent_on_row_uses_contract_default():
    row = SimpleNamespace(id="x", count=3)  # no 'label' -> contract default applies
    assert map_row(row, _Demo).label == "default"


def test_map_row_missing_required_field_raises_validation_error():
    from pydantic import ValidationError

    row = SimpleNamespace(id="x")  # 'count' is required and absent -> contract enforces
    with pytest.raises(ValidationError):
        map_row(row, _Demo)


def test_map_row_matches_explicit_construction_for_a_real_contract():
    # Proves byte-identical behaviour against the contract the publishing
    # accounts mapper builds, so the migration is equivalence-preserving.
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id="client_1",
        name="某客户",
        remark="备注",
        status="active",
        created_at=now,
        updated_at=now,
        schema_version="v1",
    )
    explicit = Client(
        id=row.id,
        name=row.name,
        remark=row.remark,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_version=row.schema_version,
    )
    assert map_row(row, Client) == explicit
