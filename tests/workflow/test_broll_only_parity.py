from __future__ import annotations

import pytest

from packages.core.contracts import RunStatus, WorkflowRun
from packages.core.workflow.temporal_adapter import _template_from_run
from packages.production.pipeline.node_sequence import BROLL_ONLY_SEQUENCE


def _run(
    *,
    workflow_template_id: str = "broll_only_v1",
    workflow_version: str = "v1",
) -> WorkflowRun:
    return WorkflowRun(
        id="run_broll_only",
        job_id="job_broll_only",
        case_id="case_demo",
        workflow_template_id=workflow_template_id,
        workflow_version=workflow_version,
        status=RunStatus.admitted,
    )


def test_template_from_broll_only_run_reconstructs_matching_template():
    template = _template_from_run(_run())

    assert template.workflow_template_id == "broll_only_v1"
    assert template.version == "v1"
    assert [spec.node_id for spec in template.nodes] == BROLL_ONLY_SEQUENCE
    assert len(template.nodes) == 13


def test_template_from_run_rejects_version_mismatch():
    with pytest.raises(RuntimeError):
        _template_from_run(_run(workflow_version="v2"))
