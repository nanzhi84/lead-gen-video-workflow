from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, Field

from packages.core.contracts import (
    Artifact,
    DegradationCode,
    ErrorCode,
    NodeError,
    NodeStatus,
    WarningCode,
    WorkflowRun,
)


def canonical_json(value: BaseModel | dict | list | str | int | float | bool | None) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manifest_hash(value: BaseModel | dict | list | str | int | float | bool | None) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class NodeExecutionError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error = NodeError(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        )


class NodeOutput(BaseModel):
    status: NodeStatus = NodeStatus.succeeded
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[WarningCode] = Field(default_factory=list)
    degradations: list[DegradationCode] = Field(default_factory=list)
    provider_invocation_ids: list[str] = Field(default_factory=list)


class WorkflowRuntimeAdapter(Protocol):
    def start_digital_human_run(
        self,
        *,
        job_id: str,
        mode: str = "new",
        from_run_id: str | None = None,
        reason: str | None = None,
    ) -> WorkflowRun:
        ...

    def cancel_run(self, run_id: str, *, force: bool = False, reason: str | None = None) -> WorkflowRun:
        ...
