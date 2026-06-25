"""Shared read helper for the CreativeIntentArtifact."""

from __future__ import annotations

from packages.core.contracts import ArtifactKind
from packages.core.contracts.artifacts import CreativeIntentArtifact


def load_creative_intent(state) -> CreativeIntentArtifact:
    art = state.artifacts.get(ArtifactKind.creative_intent)
    if art is None:
        return CreativeIntentArtifact()
    payload = art.payload if isinstance(art.payload, dict) else {}
    return CreativeIntentArtifact.model_validate(payload)
