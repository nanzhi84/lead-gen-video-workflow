"""Shared, tolerant read helper for the CreativeIntentArtifact.

A run started before the field architecture changed has a creative_intent payload
carrying now-removed keys (scene_type, density, ...). Under ``extra="forbid"`` a naive
``model_validate`` would raise on those, so we keep only currently-declared fields and
fall back to the stable ``intent`` blob if validation still fails. This is a cheap,
local migration that keeps resumed old runs working without bumping the global
node_version (which would force *every* resumed run to fully re-run).
"""

from __future__ import annotations

from pydantic import ValidationError

from packages.core.contracts import ArtifactKind
from packages.core.contracts.artifacts import CreativeIntentArtifact


def load_creative_intent(state) -> CreativeIntentArtifact:
    art = state.artifacts.get(ArtifactKind.creative_intent)
    if art is None:
        return CreativeIntentArtifact()
    payload = art.payload if isinstance(art.payload, dict) else {}
    known = {key: payload[key] for key in CreativeIntentArtifact.model_fields if key in payload}
    try:
        return CreativeIntentArtifact.model_validate(known)
    except ValidationError:
        intent = payload.get("intent")
        return CreativeIntentArtifact(intent=intent if isinstance(intent, dict) else None)
