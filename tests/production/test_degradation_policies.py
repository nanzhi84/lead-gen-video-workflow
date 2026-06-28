from __future__ import annotations

from packages.production.pipeline.degradation_policies import (
    ASR_ESTIMATED_FALLBACK_POLICY,
    COVER_FALLBACK_POLICY,
    LIPSYNC_FAILOVER_POLICY,
)


def test_degradation_policy_ids_and_versions_are_stable():
    assert LIPSYNC_FAILOVER_POLICY.id == "lipsync.failover.v1"
    assert LIPSYNC_FAILOVER_POLICY.version == "v1"
    assert ASR_ESTIMATED_FALLBACK_POLICY.id == "asr.estimated_fallback.v1"
    assert ASR_ESTIMATED_FALLBACK_POLICY.version == "v1"
    assert COVER_FALLBACK_POLICY.id == "cover.fallback.v1"
    assert COVER_FALLBACK_POLICY.version == "v1"


def test_lipsync_failover_routes_heygem_to_videoretalk_only():
    assert (
        LIPSYNC_FAILOVER_POLICY.target_provider_id("runninghub.heygem", "remote failed")
        == "dashscope.videoretalk"
    )
    assert LIPSYNC_FAILOVER_POLICY.target_provider_id("dashscope.videoretalk", "remote failed") is None
