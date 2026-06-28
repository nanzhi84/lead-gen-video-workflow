from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DegradationPolicy:
    id: str
    version: str


class LipsyncFailoverPolicy(DegradationPolicy):
    def target_provider_id(
        self,
        current_provider_id: str | None,
        error_message: str | None,
    ) -> str | None:
        # HeyGem is the primary lipsync path; VideoReTalk is the standing fallback
        # for any HeyGem provider failure. Do not fail back in the opposite
        # direction, which would create provider loops and can mask policy failures.
        _ = error_message
        if current_provider_id == "runninghub.heygem":
            return "dashscope.videoretalk"
        return None


LIPSYNC_FAILOVER_POLICY = LipsyncFailoverPolicy(
    id="lipsync.failover.v1",
    version="v1",
)
ASR_ESTIMATED_FALLBACK_POLICY = DegradationPolicy(
    id="asr.estimated_fallback.v1",
    version="v1",
)
COVER_FALLBACK_POLICY = DegradationPolicy(
    id="cover.fallback.v1",
    version="v1",
)
