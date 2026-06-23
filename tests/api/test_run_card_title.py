"""Run card title prefers the run's finished-video headline over the truncated
script prefix / persona-label request title."""

from __future__ import annotations

from apps.api.services.jobs_runs import _run_title
from packages.core import contracts as c


def _job(title, script):
    req = c.DigitalHumanVideoRequest(
        case_id="case_demo",
        title=title,
        publish_content="x",
        script=script,
        voice={"voice_id": "v"},
    )
    return c.Job(
        id="job_1",
        case_id="case_demo",
        request=req,
        type="digital_human_video",
        request_schema="DigitalHumanVideoRequest.v1",
    )


def test_run_title_prefers_finished_video_headline():
    job = _job("硬广 · 全新创作脚本", "你是不是也这样，跑遍十几家定制公司，方案越看越像")
    # A completed run carries the generated headline on its finished video; the card
    # shows it instead of the persona-label request title or the script prefix.
    assert _run_title(job, "局部修复几百块搞定") == "局部修复几百块搞定"


def test_run_title_falls_back_to_request_then_script_prefix():
    # No finished video yet (in-flight / failed run) -> request title, else script prefix.
    job = _job("硬广 · 全新创作脚本", "你是不是也这样")
    assert _run_title(job, None) == "硬广 · 全新创作脚本"

    long_script = "你是不是也这样，跑遍十几家定制公司，方案越看越像，越看越纠结"
    job2 = _job(None, long_script)
    assert _run_title(job2, None) == long_script[:28]
