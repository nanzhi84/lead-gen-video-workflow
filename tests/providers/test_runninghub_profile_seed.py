"""Regression guard: the seeded RunningHub HeyGem prod profile must carry the
HeyGem webapp's real node field names.

The adapter falls back to the generic field names ``"video"`` / ``"audio"`` when
``video_field_name`` / ``audio_field_name`` are absent (runninghub.py). The HeyGem
webapp's node 1 video input is named ``"file"`` (node 4 audio is ``"audio"``), so a
profile missing ``video_field_name`` makes RunningHub reject the /run submit with
``803 NODE_INFO_MISMATCH(nodeId=1, fieldName=video, field_not_found_in_node_inputs)``
and lipsync silently fails over to the backup provider on every run.
"""

from __future__ import annotations

from packages.core.storage.provider_seed import seed_real_provider_configuration
from packages.core.storage.repository import Repository


def test_heygem_prod_profile_seeds_node_field_names():
    repo = Repository()
    seed_real_provider_configuration(repo)

    profile = repo.provider_profiles["runninghub.heygem.prod"]
    opts = profile.default_options

    assert opts.get("video_field_name") == "file"
    assert opts.get("audio_field_name") == "audio"
