from __future__ import annotations

from projectkoios.references.identity import IdentityProjection

from .base import CitationBibliographyObservationBinding


def candidate_identity_ids_by_key(
    *,
    bindings: tuple[CitationBibliographyObservationBinding, ...],
    identity_projection: IdentityProjection,
) -> dict[str, tuple[str, ...]]:
    """Return exact observation-bound candidate IDs grouped by literal key."""
    if type(bindings) is not tuple or any(
        type(item) is not CitationBibliographyObservationBinding
        for item in bindings
    ):
        raise TypeError("bibliography bindings must use canonical exact types")
    if type(identity_projection) is not IdentityProjection:
        raise TypeError("identity_projection must be an IdentityProjection")

    candidates_by_observation: dict[str, list[str]] = {}
    candidate_by_id = {
        item.candidate_id: item for item in identity_projection.candidates
    }
    for candidate in identity_projection.candidates:
        for observation_id in candidate.source_observation_ids:
            candidates_by_observation.setdefault(
                observation_id,
                [],
            ).append(candidate.candidate_id)

    grouped: dict[str, list[str]] = {}
    for binding in bindings:
        candidate_ids = candidates_by_observation.get(
            binding.observation.observation_id,
            [],
        )
        for candidate_id in candidate_ids:
            if candidate_by_id[candidate_id].proposed_citekey == (
                binding.entry.key
            ):
                grouped.setdefault(binding.entry.key, []).append(candidate_id)
    return {
        key: tuple(sorted(set(candidate_ids)))
        for key, candidate_ids in grouped.items()
    }
