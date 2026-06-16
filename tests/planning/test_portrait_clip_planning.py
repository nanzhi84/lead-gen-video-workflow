"""P2: clip-level portrait (lip-sync A-roll) candidate ranking from a unified video.

A single mixed ``video`` annotation yields lip-sync candidates ONLY from its
talking-head clips (single-face, recommended_for_lip_sync, long enough), each
carrying its source window; its cover clips go to the b-roll pool instead, and
its talking-head clips are kept OUT of the b-roll pool.
"""

from __future__ import annotations

from packages.core.contracts import (
    AnnotationMetaV4,
    AnnotationV4,
    ClipRetrievalV4,
    ClipSemanticsV4,
    ClipUsageV4,
    ClipV4,
    UsageRole,
)
from packages.planning.material import (
    clip_is_lip_sync_usable,
    rank_broll_candidates,
    rank_portrait_clip_candidates,
)
from packages.planning.material.keywords import ScriptSegment


def _clip(
    segment_id,
    start,
    end,
    *,
    role=UsageRole.main,
    lip_sync=True,
    face_count_max=1,
    keywords=("内容",),
):
    return ClipV4(
        segment_id=segment_id,
        start=start,
        end=end,
        duration=end - start,
        semantics=ClipSemanticsV4(scene_type="场景", face_count_max=face_count_max),
        usage=ClipUsageV4(role=role, recommended_for_lip_sync=lip_sync),
        retrieval=ClipRetrievalV4(
            summary=" ".join(keywords),
            keywords=list(keywords),
            retrieval_sentence=" ".join(keywords),
        ),
        confidence=0.9,
    )


def _video_annotation(asset_id, clips):
    return AnnotationV4(
        meta=AnnotationMetaV4(
            asset_id=asset_id, case_id="case_demo", material_type="video", duration=20.0
        ),
        clips=clips,
        quality_report={"usable_ratio": 0.9, "lip_sync_suitability_score": 80},
    )


def test_clip_is_lip_sync_usable_gates():
    # usable talking head
    assert clip_is_lip_sync_usable(_clip("ok", 2.0, 9.0))
    # not recommended for lip sync (a cover clip)
    assert not clip_is_lip_sync_usable(
        _clip("cover", 0.0, 5.0, role=UsageRole.cover, lip_sync=False)
    )
    # multi-face frame -> cannot lip-sync
    assert not clip_is_lip_sync_usable(_clip("multi", 0.0, 5.0, face_count_max=2))
    # too short to anchor a narration chunk
    assert not clip_is_lip_sync_usable(_clip("tiny", 0.0, 0.4))
    # avoid role
    assert not clip_is_lip_sync_usable(_clip("avoid", 0.0, 5.0, role=UsageRole.avoid))
    # face_count_max None (CV unavailable) is fail-open -> still usable
    assert clip_is_lip_sync_usable(_clip("nofcm", 2.0, 9.0, face_count_max=None))


def test_rank_portrait_clips_picks_only_lipsync_clips_with_source_windows():
    annotation = _video_annotation(
        "vid_mixed",
        [
            _clip("talk", 2.0, 9.0),  # usable A-roll
            _clip("scenery", 9.0, 14.0, role=UsageRole.cover, lip_sync=False),  # B-roll
            _clip("mirror", 14.0, 18.0, face_count_max=2),  # multi-face -> excluded
            _clip("blip", 18.0, 18.3),  # too short -> excluded
        ],
    )
    candidates = rank_portrait_clip_candidates(
        annotations={"vid_mixed": annotation}, required_duration=0.0
    )
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.asset_id == "vid_mixed"
    assert cand.clip_id == "talk"
    # The candidate carries the talking-head clip's source window verbatim.
    assert cand.source_start == 2.0
    assert cand.source_end == 9.0
    assert cand.duration == 7.0


def test_video_talking_head_clips_stay_out_of_broll_pool():
    # A main-role lip-sync clip whose keywords match the script must NOT surface as a
    # b-roll candidate (it is A-roll); only the cover clip should.
    annotation = _video_annotation(
        "vid_mixed",
        [
            _clip("talk", 0.0, 6.0, keywords=("打磨", "工艺")),  # role=main -> excluded from b-roll
            _clip(
                "cover",
                6.0,
                10.0,
                role=UsageRole.cover,
                lip_sync=False,
                keywords=("打磨", "工艺"),
            ),
        ],
    )
    segments = [ScriptSegment(text="打磨工艺细节", start=0.0, end=4.0, keywords=("打磨", "工艺"))]
    broll = rank_broll_candidates(annotations={"vid_mixed": annotation}, segments=segments)
    clip_ids = {c.clip_id for c in broll}
    assert "talk" not in clip_ids
    assert "cover" in clip_ids


def test_video_backup_lipsync_clip_stays_out_of_broll_pool():
    annotation = _video_annotation(
        "vid_mixed",
        [
            _clip(
                "backup_talk",
                0.0,
                6.0,
                role=UsageRole.backup,
                lip_sync=True,
                keywords=("打磨", "工艺"),
            ),
            _clip(
                "cover",
                6.0,
                10.0,
                role=UsageRole.cover,
                lip_sync=False,
                keywords=("打磨", "工艺"),
            ),
        ],
    )
    portrait = rank_portrait_clip_candidates(
        annotations={"vid_mixed": annotation}, required_duration=0.0
    )
    assert {c.clip_id for c in portrait} == {"backup_talk"}

    segments = [ScriptSegment(text="打磨工艺细节", start=0.0, end=4.0, keywords=("打磨", "工艺"))]
    broll = rank_broll_candidates(annotations={"vid_mixed": annotation}, segments=segments)
    clip_ids = {c.clip_id for c in broll}
    assert "backup_talk" not in clip_ids
    assert "cover" in clip_ids
