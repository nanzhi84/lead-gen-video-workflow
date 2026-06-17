"""Real b-roll candidate ranking from AnnotationV4 clips + narration beats.

Replaces the seeded ``score=1`` b-roll pick. For every annotated b-roll asset we
turn its ``ClipV4`` clips into matchable scenes, score each against the script /
narration beats (jieba keyword similarity + clip quality + usage-window
coverage), demote recently-used assets via the selection ledger, and return
ranked candidates carrying real scores + matched keywords. No annotations ->
empty list (the node soft-degrades; never a fabricated pick).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from packages.core.contracts import AnnotationV4, SelectionLedgerEntry
from packages.media.annotation._material import is_video
from packages.planning.material.keywords import ScriptSegment
from packages.planning.material.matching import BrollScene, best_match
from packages.planning.material.portrait_pack import clip_is_lip_sync_usable
from packages.planning.selection.recency import RecencyConfig, recency_penalty_for

# Score weights (ported from the origin base_score formula, normalized to the
# same shape: semantic match dominates, quality + usage-window coverage refine).
_SEMANTIC_WEIGHT = 100.0
_USAGE_COVER_WEIGHT = 18.0
_QUALITY_WEIGHT = 8.0
_DURATION_WEIGHT = 0.5
_RECENCY_WEIGHT = 12.0
# A candidate must clear a minimal semantic relevance to be offered at all,
# otherwise an unrelated clip would still be picked (the honest alternative to
# the old "anything usable is fine" seed). A clip also has to have *real*
# semantic overlap (``MatchResult.has_overlap``) — the duration-fit tie-breaker
# alone never makes an unrelated clip relevant.
_MIN_SIMILARITY = 0.05

# Subject-type surface forms that mark a clip as person-centric (a presenter /
# talking-head / 出镜人物). Substring match against ``ClipSemanticsV4.subject_type``.
_PERSON_SUBJECT_TERMS = (
    "presenter",
    "salesperson",
    "spokes",
    "host",
    "anchor",
    "streamer",
    "influencer",
    "person",
    "people",
    "human",
    "speaker",
    "主播",
    "真人",
    "导购",
    "模特",
    "口播",
    "出镜",
    "人物",
    "讲解",
)


def clip_shows_person(clip) -> bool:
    """Whether a clip features a real person as its subject — a presenter /
    talking-head / on-camera 出镜人物 — making it unsuitable as clean b-roll cover.

    A "B-roll only" video must carry scene/product footage, not a person. A
    talking-head clip that *is* lip-sync usable is already routed to the A-roll
    pool upstream; this predicate is the content-based backstop for person clips
    that are NOT lip-sync usable (multi-face, presenter wide shots) and would
    otherwise leak into b-roll. It looks only at clip *content* — subject type,
    an explicit face flag, multiple faces (>=2), or talking-head visual cues — and
    deliberately ignores the ``recommended_for_lip_sync`` usage flag (a noisy
    legacy-b-roll signal handled by the A-roll split). A single *incidental*
    background face (``face_count_max == 1`` with no person subject) is NOT a
    person clip, so legitimate scene/product cover that merely catches one face in
    frame still qualifies as b-roll.
    """
    sem = clip.semantics
    subject = (sem.subject_type or "").lower()
    if any(term in subject for term in _PERSON_SUBJECT_TERMS):
        return True
    if sem.contains_face is True:
        return True
    fcm = sem.face_count_max
    if fcm is not None and fcm >= 2:
        return True
    if sem.mouth_moving is True or sem.gaze_to_camera is True:
        return True
    return False


@dataclass(frozen=True)
class BrollCandidate:
    asset_id: str
    clip_id: str
    score: float
    base_score: float
    recency_penalty: float
    matched_keywords: tuple[str, ...]
    scene_name: str
    source_start: float
    source_end: float
    diversity_key: str = ""
    best_segment: ScriptSegment | None = field(default=None)


def _scene_from_clip(asset_id: str, clip) -> BrollScene:
    semantics = clip.semantics
    retrieval = clip.retrieval
    name = (
        semantics.narrative_role
        or semantics.action
        or semantics.scene_type
        or retrieval.summary
        or "片段"
    ).strip()[:48] or "片段"
    description = (retrieval.retrieval_sentence or retrieval.summary or "").strip()
    keywords = tuple(kw.strip() for kw in retrieval.keywords if kw.strip())
    return BrollScene(
        clip_id=clip.segment_id,
        name=name,
        description=description,
        keywords=keywords,
        start=float(clip.start),
        end=float(clip.end),
    )


def _usage_cover_ratio(annotation: AnnotationV4, clip) -> float:
    """Fraction of the clip overlapped by a recommended usage window (0..1)."""
    if not annotation.usage_windows:
        return 0.0
    clip_span = max(0.0, float(clip.end) - float(clip.start))
    if clip_span <= 0:
        return 0.0
    covered = 0.0
    for win in annotation.usage_windows:
        lo = max(float(clip.start), float(win.start))
        hi = min(float(clip.end), float(win.end))
        if hi > lo:
            covered += hi - lo
    return min(1.0, covered / clip_span)


def _diversity_key(clip) -> str:
    return (clip.semantics.scene_type or clip.semantics.narrative_role or "").strip()


def rank_broll_candidates(
    *,
    annotations: dict[str, AnnotationV4],
    asset_kinds: dict[str, str] | None = None,
    segments: Sequence[ScriptSegment],
    ledger_entries: Sequence[SelectionLedgerEntry] = (),
    recency_cfg: RecencyConfig | None = None,
) -> list[BrollCandidate]:
    """Rank b-roll clips across annotated assets against the script beats.

    ``annotations`` maps asset_id -> AnnotationV4 (annotated b-roll/video assets).
    ``ledger_entries`` are this case's recent b-roll selections (most-recent
    first); a previously-picked asset/cluster is demoted. Returns candidates
    sorted by final score descending. Empty when nothing clears the relevance
    floor (the honest "no usable material" signal).
    """
    seg_list = list(segments)
    candidates: list[BrollCandidate] = []
    for asset_id, annotation in annotations.items():
        material_type = (asset_kinds or {}).get(asset_id) or annotation.meta.material_type
        from_unified_video = is_video(material_type)
        for clip in annotation.clips:
            # Legacy b-roll keeps the historical rule: only ``avoid`` is unusable.
            # Unified video clips are split into A-roll (lip-sync-usable) vs B-roll,
            # but B-roll must be *person-free* scene footage: a clip showing a real
            # person as its subject (presenter / talking-head / 出镜人物) belongs to
            # NEITHER pool — it is not a clean cover even when it cannot be lip-synced.
            if clip.usage.role.value == "avoid":
                continue
            if from_unified_video and clip_is_lip_sync_usable(clip):
                continue
            if clip_shows_person(clip):
                continue
            scene = _scene_from_clip(asset_id, clip)
            best_segment, match = best_match(seg_list, scene)
            if not match.has_overlap or match.similarity < _MIN_SIMILARITY:
                continue
            usage_cover = _usage_cover_ratio(annotation, clip)
            quality = float(annotation.quality_report.get("usable_ratio") or 0.5)
            duration = max(0.0, scene.end - scene.start)
            base = (
                match.similarity * _SEMANTIC_WEIGHT
                + usage_cover * _USAGE_COVER_WEIGHT
                + quality * _QUALITY_WEIGHT
                + min(duration, 8.0) * _DURATION_WEIGHT
            )
            diversity_key = _diversity_key(clip)
            penalty = recency_penalty_for(
                ledger_entries,
                asset_id=asset_id,
                diversity_key=diversity_key,
                cfg=recency_cfg,
            )
            final = max(0.0, base - penalty * _RECENCY_WEIGHT)
            candidates.append(
                BrollCandidate(
                    asset_id=asset_id,
                    clip_id=clip.segment_id,
                    score=round(final, 3),
                    base_score=round(base, 3),
                    recency_penalty=round(penalty, 3),
                    matched_keywords=match.matched_keywords,
                    scene_name=scene.name,
                    source_start=round(scene.start, 3),
                    source_end=round(scene.end, 3),
                    diversity_key=diversity_key,
                    best_segment=best_segment,
                )
            )

    candidates.sort(key=lambda c: (-c.score, c.asset_id, c.clip_id))
    return candidates
