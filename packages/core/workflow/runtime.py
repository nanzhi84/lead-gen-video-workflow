from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from packages.core.contracts import (
    Artifact,
    DegradationNotice,
    ErrorCode,
    NodeError,
    NodeStatus,
    Job,
    RunStatus,
    WarningCode,
    WorkflowRun,
    WorkflowTemplate,
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
    degradations: list[DegradationNotice] = Field(default_factory=list)
    provider_invocation_ids: list[str] = Field(default_factory=list)


class WorkflowRuntimeSettings(BaseModel):
    runtime: Literal["local", "temporal"] = "local"
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "cutagent-production"


def load_workflow_runtime_settings() -> WorkflowRuntimeSettings:
    return WorkflowRuntimeSettings(
        runtime=os.getenv("CUTAGENT_WORKFLOW_RUNTIME", "local").lower(),
        temporal_address=os.getenv("CUTAGENT_TEMPORAL_ADDRESS", "127.0.0.1:7233"),
        temporal_namespace=os.getenv("CUTAGENT_TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv("CUTAGENT_TEMPORAL_TASK_QUEUE", "cutagent-production"),
    )


class WorkflowRuntimeAdapter(Protocol):
    def start_run(
        self,
        *,
        job: Job,
        run: WorkflowRun,
        template: WorkflowTemplate,
    ) -> None:
        ...

    def cancel_run(
        self, run_id: str, *, force: bool = False, reason: str | None = None
    ) -> WorkflowRun | None:
        ...

    def resume_run(
        self,
        *,
        source_run_id: str,
        new_run: WorkflowRun,
        reuse_plan: Any,
    ) -> None:
        ...

    def get_run_status(self, run_id: str) -> RunStatus | None:
        ...
