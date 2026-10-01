from __future__ import annotations

from projectkoios.references.citation_identity import (
    CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES,
    CitationIdentityProjectionItem,
    CitationIdentityProjectionRequest,
    CitationIdentityProjectionStatus,
    CitationIdentityProjector,
)
from projectkoios.references.identity import IdentityProjection

from .base import CitationTargetGroup
from .statuses import CitationKeyResolutionStatus


def resolve_identity_ids_by_key(
    *,
    groups: tuple[CitationTargetGroup, ...],
    identity_projection: IdentityProjection,
    candidate_ids_by_key: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Apply accepted-name precedence to neutral candidate mappings."""
    if type(groups) is not tuple or any(
        type(item) is not CitationTargetGroup for item in groups
    ):
        raise TypeError("citation groups must use canonical exact types")
    if type(identity_projection) is not IdentityProjection:
        raise TypeError("identity_projection must be an IdentityProjection")
    if type(candidate_ids_by_key) is not dict or any(
        type(key) is not str
        or type(values) is not tuple
        or any(type(value) is not str for value in values)
        for key, values in candidate_ids_by_key.items()
    ):
        raise TypeError("candidate identity mappings are invalid")

    active_ids = set(identity_projection.active_reference_ids)
    accepted_by_key: dict[str, str] = {}
    for name in identity_projection.name_history:
        if not name.active or name.reference_id not in active_ids:
            continue
        if name.canonical_citekey in accepted_by_key:
            raise ValueError("active canonical citekey is ambiguous")
        accepted_by_key[name.canonical_citekey] = name.reference_id
    for alias in identity_projection.alias_history:
        if not alias.active or alias.target_reference_id not in active_ids:
            continue
        existing = accepted_by_key.get(alias.alias_citekey)
        if existing is not None and existing != alias.target_reference_id:
            raise ValueError("active citation alias is ambiguous")
        accepted_by_key[alias.alias_citekey] = alias.target_reference_id

    result: dict[str, tuple[str, ...]] = {}
    for group in groups:
        accepted = accepted_by_key.get(group.key)
        result[group.key] = (
            (accepted,)
            if accepted is not None
            else tuple(sorted(set(candidate_ids_by_key.get(group.key, ()))))
        )
    return result


def project_identity_ids(
    *,
    identity_projection: IdentityProjection,
    identity_ids: tuple[str, ...],
) -> tuple[CitationIdentityProjectionItem, ...]:
    """Project sorted identity IDs through bounded canonical batches."""
    if type(identity_projection) is not IdentityProjection:
        raise TypeError("identity_projection must be an IdentityProjection")
    if (
        type(identity_ids) is not tuple
        or identity_ids != tuple(sorted(set(identity_ids)))
        or any(type(item) is not str for item in identity_ids)
    ):
        raise ValueError("identity IDs must be a sorted unique tuple")

    values: list[CitationIdentityProjectionItem] = []
    for offset in range(
        0,
        len(identity_ids),
        CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES,
    ):
        batch = identity_ids[
            offset : offset + CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES
        ]
        if not batch:
            continue
        result = CitationIdentityProjector().project(
            request=CitationIdentityProjectionRequest(
                projection=identity_projection,
                identity_ids=batch,
            )
        )
        values.extend(result.items)
    return tuple(values)


def key_resolution_status(
    items: tuple[CitationIdentityProjectionItem, ...],
) -> CitationKeyResolutionStatus:
    """Reduce one exact projected identity tuple without first-match choice."""
    if type(items) is not tuple or any(
        type(item) is not CitationIdentityProjectionItem for item in items
    ):
        raise TypeError("identity projection items must use canonical types")
    if len(items) == 1 and items[0].status in {
        CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL,
        CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL,
    }:
        return CitationKeyResolutionStatus.RESOLVED
    if len(items) > 1 and all(
        item.status
        is CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
        for item in items
    ):
        return CitationKeyResolutionStatus.AMBIGUOUS
    if not items:
        return CitationKeyResolutionStatus.UNRESOLVED
    raise ValueError("literal key identity projection is inconsistent")
