"""Performance scoring and creative feature extraction helpers."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from packages.core.contracts import (
    CreativeFeatureVector,
    PerformanceObservation,
    PerformanceScore,
    ScriptVersion,
    VideoVersion,
)

# §25.6: below this impression/view volume we never write a high-confidence
# conclusion (impressions/views must not be treated as quality directly).
MIN_CONFIDENT_IMPRESSIONS = 1000

# §25.6: 24h is only an early signal; later windows may feed rubric calibration.
EARLY_SIGNAL_WINDOWS = frozenset({"1h", "24h"})


# §25.6 PerformanceScore

def _engagement_rate(obs: PerformanceObservation) -> float | None:
    parts = [obs.like_rate, obs.comment_rate, obs.share_rate, obs.follow_rate]
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return sum(present)


def _primary_metric_value(
    obs: PerformanceObservation,
) -> tuple[str, float | None]:
    """Pick the most meaningful normalized signal available on the observation."""
    if obs.conversion_rate is not None:
        return "conversion_rate", obs.conversion_rate
    if obs.follow_rate is not None:
        return "follow_rate", obs.follow_rate
    if obs.completion_rate is not None:
        return "completion_rate", obs.completion_rate
    engagement = _engagement_rate(obs)
    if engagement is not None:
        return "engagement_rate", engagement
    return "engagement_rate", None


def _impression_volume(obs: PerformanceObservation) -> int:
    candidates = [obs.impressions, obs.views]
    values = [int(v) for v in candidates if v is not None]
    if values:
        return max(values)
    # Fall back to the generic metric value for views/impressions rows.
    if obs.metric_name in {"views", "impressions"}:
        return int(obs.metric_value)
    return 0


def compute_performance_score(obs: PerformanceObservation) -> PerformanceScore:
    """Compute a §25.6 normalized, windowed, confidence-gated PerformanceScore."""
    window = obs.window or "7d"
    primary_metric, raw = _primary_metric_value(obs)
    volume = _impression_volume(obs)

    excluded_reason: str | None = None
    normalized = 0.0 if raw is None else max(0.0, min(1.0, float(raw)))

    # Confidence starts from volume sufficiency and is degraded for early signals
    # and missing primary metrics so we never over-trust raw view counts.
    if raw is None:
        confidence = 0.0
        excluded_reason = "no_normalized_metric"
    elif volume < MIN_CONFIDENT_IMPRESSIONS:
        confidence = 0.2
        excluded_reason = "low_impressions"
    elif window in EARLY_SIGNAL_WINDOWS:
        confidence = 0.4
        excluded_reason = "early_signal_window"
    else:
        # Scale confidence with volume (saturating) for mature windows.
        confidence = min(1.0, 0.6 + 0.4 * min(1.0, volume / (MIN_CONFIDENT_IMPRESSIONS * 10)))

    sample_size = 1 if volume > 0 or raw is not None else 0

    return PerformanceScore(
        id=f"pscore_{obs.id}",
        observation_id=obs.id,
        case_id=obs.case_id,
        video_version_id=obs.video_version_id,
        platform=obs.platform,
        account_id=obs.account_id,
        window=window,
        primary_metric=primary_metric,  # type: ignore[arg-type]
        normalized_score=normalized,
        confidence=confidence,
        sample_size=sample_size,
        excluded_reason=excluded_reason,
    )


# §25.5 Feature extraction

_HOOK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("question", r"[?？]"),
    ("number", r"\d"),
    ("pain_point", r"痛点|烦恼|难题|problem|struggle"),
    ("contrast", r"但是|然而|没想到|but |however"),
)

_CTA_PATTERNS: tuple[tuple[str, str], ...] = (
    ("link_in_bio", r"主页|简介|link in bio|bio"),
    ("follow", r"关注|follow"),
    ("comment", r"评论|留言|comment"),
    ("buy", r"购买|下单|buy|order|购物车"),
    ("dm", r"私信|私我|dm"),
)


def _first_sentence(text: str) -> str:
    parts = re.split(r"[。!?\n.!?]", text.strip())
    for part in parts:
        if part.strip():
            return part.strip()
    return text.strip()[:80]


def _detect(patterns: Sequence[tuple[str, str]], text: str) -> str | None:
    lowered = text.lower()
    for label, pattern in patterns:
        if re.search(pattern, lowered):
            return label
    return None


def _script_structure(text: str) -> str | None:
    line_count = len([line for line in text.splitlines() if line.strip()])
    if not text.strip():
        return None
    if line_count >= 3:
        return "multi_beat"
    if re.search(r"首先|其次|最后|step", text.lower()):
        return "listicle"
    return "single_beat"


def _topic_tags(text: str, *, extra: Iterable[str] = ()) -> list[str]:
    tags: list[str] = []
    for token in extra:
        token = (token or "").strip()
        if token and token not in tags:
            tags.append(token)
    # Cheap keyword extraction: pick distinct Chinese 2-grams / Latin words.
    words = re.findall(r"[A-Za-z]{4,}|[一-鿿]{2,4}", text)
    for word in words:
        if word not in tags:
            tags.append(word)
        if len(tags) >= 8:
            break
    return tags[:8]


def extract_script_features(
    script: ScriptVersion,
    *,
    case_id: str,
    feature_id: str,
    creative_intent: dict | None = None,
) -> CreativeFeatureVector:
    """ScriptFeatureExtractionNode (§25.5): partial vector from ScriptVersion."""
    text = script.script or ""
    intent = creative_intent or {}
    hook = _detect(_HOOK_PATTERNS, _first_sentence(text)) or "statement"
    cta = _detect(_CTA_PATTERNS, text)
    angle = intent.get("angle") if isinstance(intent, dict) else None
    return CreativeFeatureVector(
        id=feature_id,
        case_id=case_id,
        script_version_id=script.id,
        hook_type=hook,
        script_structure=_script_structure(text),
        topic_tags=_topic_tags(text, extra=[str(intent.get("topic"))] if intent.get("topic") else []),
        cta_type=cta,
        angle=str(angle) if angle else None,
        title_tokens=len(re.findall(r"\S+", script.title or "")),
    )


def extract_video_features(
    video: VideoVersion,
    *,
    feature_id: str,
    partial: CreativeFeatureVector | None = None,
    timeline_plan: dict | None = None,
    style_plan: dict | None = None,
) -> CreativeFeatureVector:
    """VideoFeatureExtractionNode (§25.5): complete vector from VideoVersion + plans."""
    base = partial.model_copy() if partial is not None else CreativeFeatureVector(
        id=feature_id, case_id=video.case_id
    )
    timeline = timeline_plan or {}
    style = style_plan or {}

    segments = timeline.get("segments")
    cuts = len(segments) if isinstance(segments, list) else None
    duration = None
    broll_count = base.broll_count
    material_ids: list[str] = list(base.material_ids)
    if isinstance(segments, list):
        durations = [
            float(seg.get("duration_sec", 0) or 0)
            for seg in segments
            if isinstance(seg, dict)
        ]
        duration = sum(durations) or None
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            if seg.get("kind") == "broll" or seg.get("type") == "broll":
                broll_count += 1
            mat = seg.get("material_id")
            if mat and mat not in material_ids:
                material_ids.append(str(mat))

    cut_density = (cuts / duration) if (cuts and duration) else None
    broll_density = (broll_count / duration) if (broll_count and duration) else None

    update = {
        "id": feature_id,
        "case_id": video.case_id,
        "video_version_id": video.id,
        "script_version_id": base.script_version_id or video.script_version_id,
        "duration_sec": duration if duration is not None else base.duration_sec,
        "cut_density": cut_density if cut_density is not None else base.cut_density,
        "broll_density": broll_density if broll_density is not None else base.broll_density,
        "broll_count": broll_count,
        "material_ids": material_ids,
        "subtitle_style_id": (style.get("subtitle_style_id") if isinstance(style, dict) else None)
        or base.subtitle_style_id,
        "bgm_id": (style.get("bgm_id") if isinstance(style, dict) else None) or base.bgm_id,
        "cover_style": (style.get("cover_style") if isinstance(style, dict) else None)
        or base.cover_style,
    }
    return base.model_copy(update=update)
