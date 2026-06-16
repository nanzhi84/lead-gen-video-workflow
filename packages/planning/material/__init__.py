"""Material planning domain: real candidate ranking + b-roll insertion planning.

Pure deterministic functions that take ``AnnotationV4`` clips + narration units
(+ the selection ledger for recency) and produce real material packs and b-roll
insertion plans. No IO, no randomness, no fabricated picks — when annotations /
material are absent the caller soft-degrades.
"""

from packages.planning.material.broll_pack import BrollCandidate, rank_broll_candidates
from packages.planning.material.broll_plan import BrollInsertion, plan_insertions
from packages.planning.material.keywords import (
    ScriptSegment,
    extract_keywords,
    segment_script,
)
from packages.planning.material.matching import BrollScene, MatchResult, best_match, score_segment
from packages.planning.material.portrait_pack import (
    PortraitClipCandidate,
    SimpleCandidate,
    clip_is_lip_sync_usable,
    rank_portrait_clip_candidates,
    score_simple_candidate,
)

__all__ = [
    "BrollCandidate",
    "rank_broll_candidates",
    "BrollInsertion",
    "plan_insertions",
    "ScriptSegment",
    "extract_keywords",
    "segment_script",
    "BrollScene",
    "MatchResult",
    "best_match",
    "score_segment",
    "SimpleCandidate",
    "PortraitClipCandidate",
    "clip_is_lip_sync_usable",
    "rank_portrait_clip_candidates",
    "score_simple_candidate",
]
