"""Case rubric self-evolution pure logic (case_rubric_v1).

The "memory" of a case is an executable scoring card (``CaseRubric``): weighted
dimensions over a script's ``CreativeFeatureVector``. This module is the storage-
agnostic core shared by the in-memory and SQLAlchemy service paths:

- ``cold_start_rubric`` (§4.3/§12): an industry-default card so a brand-new case
  can already score & rank drafts before any reward data exists.
- ``score`` / ``predict`` (§6.1/§6.2): blind composite + band + a human-readable
  reason; the prediction reads only script features, never real metrics.
- ``reward_value`` (§5.2): stage/选择 → reward shaping (values come from
  ``LearningSettings`` so they are tunable, not magic numbers).
- ``evaluate_calibration`` (§6.3): ranking consistency + miss-streak over reward-
  labeled predictions; recommends a bump when the gate trips.
- ``fit_weights`` / ``propose_bump`` (§6.4): deterministically refit weights &
  value-scores from reward samples, and only propose an upgrade when the new card
  *reranks the calibration pool strictly more accurately* (anti-self-deception).

Everything is deterministic: no DB, provider calls, or randomness.
"""

from __future__ import annotations

from typing import Sequence

from packages.core.config.settings import LearningSettings
from packages.core.contracts import (
    CalibrationReport,
    CaseRubric,
    CreativeFeatureVector,
    RewardSourceKind,
    RubricBumpProposal,
    RubricDimension,
    ScoreBand,
    ScorePrediction,
)

# §6.1 band thresholds on the 0–10 composite.
BAND_TOP_MIN = 7.5
BAND_OK_MIN = 5.0

# §6.3 a reward-labeled prediction counts as a miss when blind composite and the
# latest reward signal disagree by at least this much.
MISS_DELTA = 0.3

# A reward sample: prediction features plus the latest training reward.
RewardSample = tuple[CreativeFeatureVector, float]


# ---------------------------------------------------------------------------
# Cold-start card
# ---------------------------------------------------------------------------

def starter_dimensions() -> list[RubricDimension]:
    """Industry-default dimensions for a hard-ad / 投流 case (§12 P0).

    Weights favour a strong hook and a clear conversion CTA — the two levers
    投流 operators care about most. Reused as the base for every refit, so the
    keys must align with ``CreativeFeatureVector`` field names.
    """
    return [
        RubricDimension(
            key="hook_type",
            label="开场强度",
            weight=0.35,
            kind="categorical",
            value_scores={
                "pain_point": 1.0,
                "question": 0.9,
                "number": 0.8,
                "contrast": 0.8,
                "statement": 0.4,
            },
        ),
        RubricDimension(
            key="cta_type",
            label="转化引导",
            weight=0.35,
            kind="categorical",
            value_scores={
                "buy": 1.0,
                "link_in_bio": 0.9,
                "dm": 0.7,
                "comment": 0.5,
                "follow": 0.5,
            },
        ),
        RubricDimension(
            key="script_structure",
            label="脚本结构",
            weight=0.20,
            kind="categorical",
            value_scores={"multi_beat": 0.9, "listicle": 0.8, "single_beat": 0.5},
        ),
        RubricDimension(
            key="duration_sec",
            label="时长",
            weight=0.10,
            kind="numeric",
            numeric_low=15.0,
            numeric_high=45.0,
        ),
    ]


def cold_start_rubric(*, rubric_id: str, case_id: str) -> CaseRubric:
    """A fresh, uncalibrated active card so a new case can score immediately."""
    return CaseRubric(
        id=rubric_id,
        case_id=case_id,
        version=1,
        status="active",
        dimensions=starter_dimensions(),
        fitted_from_sample_size=0,
        cold_start=True,
    )


# ---------------------------------------------------------------------------
# §6.1 scoring
# ---------------------------------------------------------------------------

def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _numeric_score(dimension: RubricDimension, value: float | None) -> float:
    """Score a numeric feature: 1.0 inside [low, high], linearly decaying outside."""
    if value is None or dimension.numeric_low is None or dimension.numeric_high is None:
        return 0.0
    v = float(value)
    low, high = dimension.numeric_low, dimension.numeric_high
    if low <= v <= high:
        return 1.0
    if v < low:
        return _clamp01(v / low) if low > 0 else 0.0
    return _clamp01(1.0 - (v - high) / high) if high > 0 else 0.0


def _dimension_score(dimension: RubricDimension, features: CreativeFeatureVector) -> float:
    value = getattr(features, dimension.key, None)
    if dimension.kind == "numeric":
        return _numeric_score(dimension, value)
    if value is None:
        return 0.0
    return _clamp01(float(dimension.value_scores.get(str(value), 0.0)))


def composite_for(
    rubric: CaseRubric, features: CreativeFeatureVector
) -> tuple[float, dict[str, float]]:
    """Weighted composite on 0–10 plus the per-dimension [0,1] scores."""
    total_weight = sum(d.weight for d in rubric.dimensions) or 1.0
    dimension_scores: dict[str, float] = {}
    accumulated = 0.0
    for dimension in rubric.dimensions:
        s = _dimension_score(dimension, features)
        dimension_scores[dimension.key] = round(s, 4)
        accumulated += dimension.weight * s
    composite = round(10.0 * accumulated / total_weight, 2)
    return composite, dimension_scores


def band_for(composite: float) -> ScoreBand:
    if composite >= BAND_TOP_MIN:
        return "top"
    if composite >= BAND_OK_MIN:
        return "ok"
    return "low"


def _reason(rubric: CaseRubric, dimension_scores: dict[str, float]) -> str:
    """A short human-readable why, from the strongest / weakest weighted dims."""
    labels = {d.key: d.label for d in rubric.dimensions}
    weights = {d.key: d.weight for d in rubric.dimensions}
    contributions = sorted(
        dimension_scores.items(),
        key=lambda kv: weights.get(kv[0], 0.0) * kv[1],
        reverse=True,
    )
    strengths = [labels.get(k, k) for k, s in contributions if s >= 0.7][:2]
    weak = [labels.get(k, k) for k, s in contributions if s < 0.4][-1:]
    parts: list[str] = []
    if strengths:
        parts.append("、".join(strengths) + "突出")
    if weak:
        parts.append("但" + "、".join(weak) + "偏弱")
    return "；".join(parts) if parts else "各维度表现平平"


def predict(
    rubric: CaseRubric,
    features: CreativeFeatureVector,
    *,
    prediction_id: str,
    case_id: str,
    script_draft_id: str | None = None,
    script_version_id: str | None = None,
) -> ScorePrediction:
    """§6.2 blind prediction: composite/band/reason from features only."""
    composite, dimension_scores = composite_for(rubric, features)
    return ScorePrediction(
        id=prediction_id,
        case_id=case_id,
        script_draft_id=script_draft_id,
        script_version_id=script_version_id,
        rubric_version=rubric.version,
        composite=composite,
        band=band_for(composite),
        dimension_scores=dimension_scores,
        reason=_reason(rubric, dimension_scores),
    )


# ---------------------------------------------------------------------------
# §5.2 reward shaping
# ---------------------------------------------------------------------------

def reward_value(
    source_kind: RewardSourceKind,
    settings: LearningSettings,
    *,
    normalized_score: float | None = None,
    reason: str | None = None,
) -> tuple[float, float]:
    """Map a human action / stage into a (value, default_confidence) reward.

    For ``performance_scored`` the value is the normalized PerformanceScore and the
    caller should replace the confidence with that score's own confidence (which
    already carries the §25.6 volume/window gating).
    """
    table: dict[str, tuple[float, float]] = {
        "draft_adopted": (settings.reward_draft_adopted, 0.4),
        "draft_pick": (settings.reward_draft_pick, 0.3),
        "video_produced": (settings.reward_video_produced, 0.6),
        "published": (settings.reward_published, 0.8),
        "stale_unpublished": (settings.reward_stale_unpublished, 0.3),
    }
    if source_kind in table:
        return table[source_kind]
    if source_kind == "video_discarded":
        # Only "脚本不行" blames the script; other reasons are not charged (§5.2).
        value = settings.reward_video_discarded_script if reason == "script" else 0.0
        return value, 0.5
    if source_kind == "performance_scored":
        return float(normalized_score or 0.0), 0.0
    return 0.0, 0.0


# ---------------------------------------------------------------------------
# §6.3 calibration + §6.4 bump
# ---------------------------------------------------------------------------

def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / ((vx ** 0.5) * (vy ** 0.5))


def consistency(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Pairwise rank concordance between predicted composite and actual reward.

    Returns the fraction of comparable ordered pairs that agree in direction, in
    [0,1]; ``None`` when there are fewer than 2 comparable pairs.
    """
    n = len(pairs)
    if n < 2:
        return None
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            dp = pairs[i][0] - pairs[j][0]
            dr = pairs[i][1] - pairs[j][1]
            if dp == 0 or dr == 0:
                continue
            if (dp > 0) == (dr > 0):
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return None
    return concordant / total


def consistency_for_rubric(rubric: CaseRubric, samples: Sequence[RewardSample]) -> float | None:
    """Re-score every sample with ``rubric`` and measure ranking consistency."""
    pairs = [(composite_for(rubric, fv)[0], reward) for fv, reward in samples]
    return consistency(pairs)


def evaluate_calibration(
    labeled_predictions: Sequence[ScorePrediction],
    *,
    rubric: CaseRubric,
    settings: LearningSettings,
    pending_retro_count: int = 0,
) -> CalibrationReport:
    """§6.3 build the calibration report from reward-labeled blind predictions."""
    settled = [p for p in labeled_predictions if p.settled_reward is not None]
    settled = sorted(settled, key=lambda p: p.settled_at or p.locked_at)
    pairs = [(p.composite, float(p.settled_reward)) for p in settled]
    cons = consistency(pairs)

    miss_streak = 0
    for prediction in reversed(settled):
        predicted_norm = prediction.composite / 10.0
        if abs(predicted_norm - float(prediction.settled_reward)) >= MISS_DELTA:
            miss_streak += 1
        else:
            break

    sample_size = len(settled)
    bump_recommended = sample_size >= settings.bump_min_samples and (
        (cons is not None and cons < settings.bump_consistency_floor)
        or miss_streak >= settings.bump_miss_streak
    )
    return CalibrationReport(
        case_id=rubric.case_id,
        rubric_version=rubric.version,
        sample_size=sample_size,
        consistency=round(cons, 4) if cons is not None else None,
        miss_streak=miss_streak,
        pending_retro_count=pending_retro_count,
        bump_recommended=bump_recommended,
    )


def fit_weights(
    samples: Sequence[RewardSample], base_dimensions: Sequence[RubricDimension]
) -> list[RubricDimension]:
    """Deterministically refit value-scores + weights from reward samples (§6.4).

    - categorical: each observed value's score becomes the mean reward of samples
      carrying it (clamped), keeping base scores for unseen values.
    - weight: proportional to |corr(dimension score, reward)| over the samples —
      a dimension that discriminates reward gets more weight. Degenerate inputs
      fall back to equal weights so we never emit an all-zero card.
    """
    refitted: list[RubricDimension] = []
    raw_weight: dict[str, float] = {}
    for dimension in base_dimensions:
        updated = dimension
        if dimension.kind == "categorical":
            buckets: dict[str, list[float]] = {}
            for features, reward in samples:
                value = getattr(features, dimension.key, None)
                if value is None:
                    continue
                buckets.setdefault(str(value), []).append(reward)
            value_scores = dict(dimension.value_scores)
            for value, rewards in buckets.items():
                value_scores[value] = round(_clamp01(sum(rewards) / len(rewards)), 4)
            updated = dimension.model_copy(update={"value_scores": value_scores})
        xs = [_dimension_score(updated, features) for features, _ in samples]
        ys = [reward for _, reward in samples]
        raw_weight[dimension.key] = abs(_pearson(xs, ys))
        refitted.append(updated)

    total = sum(raw_weight.values())
    if total <= 0:
        equal = round(1.0 / len(refitted), 4) if refitted else 0.0
        return [d.model_copy(update={"weight": equal}) for d in refitted]
    return [
        d.model_copy(update={"weight": round(raw_weight[d.key] / total, 4)})
        for d in refitted
    ]


def propose_bump(
    active_rubric: CaseRubric,
    samples: Sequence[RewardSample],
    *,
    settings: LearningSettings,
    proposal_id: str,
    candidate_id: str,
) -> RubricBumpProposal | None:
    """§6.4 propose an upgrade only if it reranks the pool strictly more accurately.

    Guardrails: needs ``bump_min_samples`` calibration samples; re-scores ALL of
    them with both the old card and the freshly-fitted candidate; returns ``None``
    (no nag) unless the candidate's ranking consistency strictly exceeds the old.
    """
    if len(samples) < settings.bump_min_samples:
        return None
    candidate_dimensions = fit_weights(samples, active_rubric.dimensions)
    candidate = CaseRubric(
        id=candidate_id,
        case_id=active_rubric.case_id,
        version=active_rubric.version + 1,
        status="draft",
        dimensions=candidate_dimensions,
        fitted_from_sample_size=len(samples),
        cold_start=False,
        supersedes_version=active_rubric.version,
    )
    old_consistency = consistency_for_rubric(active_rubric, samples)
    new_consistency = consistency_for_rubric(candidate, samples)
    if old_consistency is None or new_consistency is None or new_consistency <= old_consistency:
        return None
    return RubricBumpProposal(
        id=proposal_id,
        case_id=active_rubric.case_id,
        status="proposed",
        from_version=active_rubric.version,
        candidate=candidate,
        old_consistency=round(old_consistency, 4),
        new_consistency=round(new_consistency, 4),
        sample_size=len(samples),
        rationale=_bump_rationale(active_rubric, candidate),
    )


def _bump_rationale(active: CaseRubric, candidate: CaseRubric) -> str:
    """Plain-language summary of the biggest weight shift driving the bump."""
    old_w = {d.key: d.weight for d in active.dimensions}
    labels = {d.key: d.label for d in candidate.dimensions}
    shifts = sorted(
        ((d.key, d.weight - old_w.get(d.key, 0.0)) for d in candidate.dimensions),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )
    if not shifts or abs(shifts[0][1]) < 1e-9:
        return "重排校准样本后整体更贴近真实表现。"
    key, delta = shifts[0]
    direction = "更看重" if delta > 0 else "更弱化"
    return f"近期数据显示「{labels.get(key, key)}」与表现更相关，建议{direction}它。"
