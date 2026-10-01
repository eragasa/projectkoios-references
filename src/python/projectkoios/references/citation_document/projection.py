from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.citation_identity import (
    CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES,
    CitationIdentityProjectionItem,
    CitationIdentityProjectionRequest,
    CitationIdentityProjectionStatus,
    CitationIdentityProjector,
)
from projectkoios.references.identity import (
    IdentityProjection,
    replay_identity_decisions,
)

from ._contract import (
    CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS,
    CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES,
    CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
    CITATION_DOCUMENT_MAX_KEYS,
    CITATION_DOCUMENT_MAX_LINKS,
    CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY,
    CITATION_DOCUMENT_MAX_OCCURRENCES,
    CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS,
    CITATION_DOCUMENT_MAX_SOURCE_GAPS,
    CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
    CITATION_DOCUMENT_PROJECTOR_NAME,
    _CitationDocumentContract,
    stable_id,
    validate_literal_citekey,
)
from .document import (
    CitationSourceDocumentDescriptor,
    CitationSourceDocumentObservation,
)
from .statuses import (
    CitationBibliographyMembershipStatus,
    CitationDocumentAvailabilityStatus,
    CitationKeyResolutionStatus,
)
from .target import (
    CitationBibliographyObservationBinding,
    CitationTargetGroup,
    CitationTargetSnapshot,
    CitationTargetSourceGap,
)

if TYPE_CHECKING:
    from .linkage import (
        CitationSourceDocumentLink,
        CitationSourceDocumentLinkResult,
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentProjectionItem(DataObjectModel):
    """One literal key with every occurrence and orthogonal owner states."""

    target_snapshot_id: str
    identity_projection_id: str
    literal_citekey: str
    occurrence_ids: tuple[str, ...]
    bibliography_membership_status: CitationBibliographyMembershipStatus
    key_resolution_status: CitationKeyResolutionStatus
    identity_items: tuple[CitationIdentityProjectionItem, ...]
    document_status: CitationDocumentAvailabilityStatus
    source_document_ids: tuple[str, ...]
    source_document_link_ids: tuple[str, ...]
    item_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.target_snapshot_id,
            kind="snapshot",
            field_name="projection item target snapshot identity",
        )
        _CitationDocumentContract.opaque_id(
            self.identity_projection_id,
            field_name="projection item identity projection",
        )
        validate_literal_citekey(
            self.literal_citekey,
            field_name="projection literal key",
        )
        if (
            type(self.occurrence_ids) is not tuple
            or not self.occurrence_ids
            or len(self.occurrence_ids) > CITATION_DOCUMENT_MAX_OCCURRENCES
            or len(self.occurrence_ids) != len(set(self.occurrence_ids))
        ):
            raise ValueError("projection occurrence identities are invalid")
        for identity in self.occurrence_ids:
            _CitationDocumentContract.target_id(
                identity,
                kind="occurrence",
                field_name="projection occurrence identity",
            )
        if (
            type(self.bibliography_membership_status)
            is not CitationBibliographyMembershipStatus
        ):
            raise TypeError("bibliography membership status is invalid")
        if type(self.key_resolution_status) is not CitationKeyResolutionStatus:
            raise TypeError("key resolution status is invalid")
        if (
            type(self.identity_items) is not tuple
            or len(self.identity_items)
            > CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES
            or any(
                type(item) is not CitationIdentityProjectionItem
                for item in self.identity_items
            )
        ):
            raise TypeError("identity projection items are invalid")
        requested_ids = tuple(
            item.requested_identity_id for item in self.identity_items
        )
        if requested_ids != tuple(sorted(set(requested_ids))):
            raise ValueError("identity projection items are not canonical")
        if any(
            item.projection_id != self.identity_projection_id
            for item in self.identity_items
        ):
            raise ValueError("identity projection item source conflicts")
        self._validate_key_resolution()
        if type(self.document_status) is not CitationDocumentAvailabilityStatus:
            raise TypeError("document availability status is invalid")
        for values, field_name, maximum in (
            (
                self.source_document_ids,
                "source document identities",
                CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
            ),
            (
                self.source_document_link_ids,
                "source document link identities",
                CITATION_DOCUMENT_MAX_LINKS,
            ),
        ):
            if (
                type(values) is not tuple
                or len(values) > maximum
                or values != tuple(sorted(set(values)))
            ):
                raise ValueError(f"{field_name} are not canonical")
            for identity in values:
                _CitationDocumentContract.opaque_id(
                    identity,
                    field_name=field_name,
                )
        self._validate_document_shape()
        object.__setattr__(
            self,
            "item_id",
            stable_id(
                "citation-document-projection-item",
                self.identity_payload(),
            ),
        )

    def _validate_key_resolution(self) -> None:
        if self.key_resolution_status is CitationKeyResolutionStatus.RESOLVED:
            if len(self.identity_items) != 1 or self.identity_items[
                0
            ].status not in {
                CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL,
                CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL,
            }:
                raise ValueError("resolved key identity items are invalid")
        elif self.key_resolution_status is (
            CitationKeyResolutionStatus.AMBIGUOUS
        ):
            if len(self.identity_items) < 2 or any(
                item.status
                is not (
                    CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
                )
                for item in self.identity_items
            ):
                raise ValueError("ambiguous key identity items are invalid")
        elif self.identity_items:
            raise ValueError("unresolved key cannot carry identity items")

    def _validate_document_shape(self) -> None:
        if (
            self.document_status
            is CitationDocumentAvailabilityStatus.NOT_OBSERVED
            and self.key_resolution_status
            is not CitationKeyResolutionStatus.RESOLVED
        ):
            raise ValueError("not-observed requires a resolved identity")
        if self.document_status in {
            CitationDocumentAvailabilityStatus.NOT_EVALUATED,
            CitationDocumentAvailabilityStatus.NOT_OBSERVED,
            CitationDocumentAvailabilityStatus.INACCESSIBLE,
        } and (self.source_document_ids or self.source_document_link_ids):
            raise ValueError(
                "document status conflicts with document identities"
            )
        if self.document_status is (
            CitationDocumentAvailabilityStatus.AVAILABLE_UNVERIFIED_LINKAGE
        ) and (not self.source_document_ids or self.source_document_link_ids):
            raise ValueError("unverified availability fields are invalid")
        if self.document_status is (
            CitationDocumentAvailabilityStatus.AVAILABLE_LINKED
        ) and (
            not self.source_document_ids or not self.source_document_link_ids
        ):
            raise ValueError("linked availability fields are invalid")
        if self.document_status is CitationDocumentAvailabilityStatus.AMBIGUOUS:
            if not self.source_document_ids:
                raise ValueError("ambiguous document status needs documents")

    def identity_payload(self) -> dict[str, object]:
        return {
            "target_snapshot_id": self.target_snapshot_id,
            "identity_projection_id": self.identity_projection_id,
            "literal_citekey": self.literal_citekey,
            "occurrence_ids": list(self.occurrence_ids),
            "bibliography_membership_status": (
                self.bibliography_membership_status.value
            ),
            "key_resolution_status": self.key_resolution_status.value,
            "identity_item_ids": [item.item_id for item in self.identity_items],
            "document_status": self.document_status.value,
            "source_document_ids": list(self.source_document_ids),
            "source_document_link_ids": list(self.source_document_link_ids),
        }


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentProjection(DataObjectModel):
    """Canonical unversioned citation/document owner projection."""

    contract_id: str
    target_snapshot_id: str
    target_projection_id: str
    bibliography_binding_ids: tuple[str, ...]
    identity_projection_id: str
    document_observation_ids: tuple[str, ...]
    source_document_link_ids: tuple[str, ...]
    source_documents: tuple[CitationSourceDocumentDescriptor, ...]
    items: tuple[CitationDocumentProjectionItem, ...]
    source_gaps: tuple[CitationTargetSourceGap, ...]
    limitations: tuple[str, ...]
    projection_id: str

    def __post_init__(self) -> None:
        if (
            type(self.contract_id) is not str
            or self.contract_id != CITATION_DOCUMENT_PROJECTION_CONTRACT_ID
        ):
            raise ValueError("citation document projection contract conflicts")
        _CitationDocumentContract.target_id(
            self.target_snapshot_id,
            kind="snapshot",
            field_name="citation document target snapshot identity",
        )
        for value, field_name in (
            (self.target_projection_id, "target projection identity"),
            (self.identity_projection_id, "identity projection identity"),
        ):
            _CitationDocumentContract.opaque_id(value, field_name=field_name)
        for values, field_name, maximum in (
            (
                self.bibliography_binding_ids,
                "bibliography binding identities",
                CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES,
            ),
            (
                self.document_observation_ids,
                "document observation identities",
                CITATION_DOCUMENT_MAX_KEYS,
            ),
            (
                self.source_document_link_ids,
                "source document link identities",
                CITATION_DOCUMENT_MAX_LINKS,
            ),
        ):
            if (
                type(values) is not tuple
                or len(values) > maximum
                or values != tuple(sorted(set(values)))
            ):
                raise ValueError(f"{field_name} are not canonical")
            for identity in values:
                _CitationDocumentContract.opaque_id(
                    identity,
                    field_name=field_name,
                )
        if (
            type(self.source_documents) is not tuple
            or len(self.source_documents)
            > CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS
            or any(
                type(item) is not CitationSourceDocumentDescriptor
                for item in self.source_documents
            )
        ):
            raise TypeError("projection source documents are invalid")
        descriptor_ids = tuple(
            item.descriptor_id for item in self.source_documents
        )
        source_document_ids = tuple(
            item.source_document_id for item in self.source_documents
        )
        if descriptor_ids != tuple(sorted(set(descriptor_ids))) or len(
            source_document_ids
        ) != len(set(source_document_ids)):
            raise ValueError("projection source documents are not canonical")
        if (
            type(self.items) is not tuple
            or len(self.items) > CITATION_DOCUMENT_MAX_KEYS
            or any(
                type(item) is not CitationDocumentProjectionItem
                for item in self.items
            )
        ):
            raise TypeError("citation document projection items are invalid")
        keys = tuple(item.literal_citekey for item in self.items)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("projection items are not key-canonical")
        if any(
            item.target_snapshot_id != self.target_snapshot_id
            or item.identity_projection_id != self.identity_projection_id
            for item in self.items
        ):
            raise ValueError("projection item source identity conflicts")
        occurrence_ids = tuple(
            occurrence_id
            for item in self.items
            for occurrence_id in item.occurrence_ids
        )
        item_ids = tuple(item.item_id for item in self.items)
        if len(occurrence_ids) != len(set(occurrence_ids)) or len(
            item_ids
        ) != len(set(item_ids)):
            raise ValueError("projection item identities overlap")
        known_source_documents = set(source_document_ids)
        known_links = set(self.source_document_link_ids)
        if any(
            not set(item.source_document_ids) <= known_source_documents
            or not set(item.source_document_link_ids) <= known_links
            for item in self.items
        ):
            raise ValueError("projection item document identities are unknown")
        if (
            type(self.source_gaps) is not tuple
            or len(self.source_gaps) > CITATION_DOCUMENT_MAX_SOURCE_GAPS
            or any(
                type(item) is not CitationTargetSourceGap
                for item in self.source_gaps
            )
        ):
            raise TypeError("citation source gaps are invalid")
        _CitationDocumentContract.sequential_indexes(
            self.source_gaps,
            attribute="source_gap_index",
            field_name="citation source gaps",
        )
        if len({item.source_gap_id for item in self.source_gaps}) != len(
            self.source_gaps
        ):
            raise ValueError("citation source gaps overlap")
        if (
            type(self.limitations) is not tuple
            or any(type(item) is not str for item in self.limitations)
            or self.limitations != self.expected_limitations()
        ):
            raise ValueError("citation document limitations are invalid")
        self.validate_identity()

    @staticmethod
    def expected_limitations() -> tuple[str, ...]:
        return (
            "not-ingestion-status",
            "not-manuscript-use-authorization",
            "not-private-processing-admission",
            "not-publication-authorization",
            "not-review-decision",
            "not-rights-clearance",
            "not-scientific-support",
            "not-search-admission",
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "target_snapshot_id": self.target_snapshot_id,
            "target_projection_id": self.target_projection_id,
            "bibliography_binding_ids": list(self.bibliography_binding_ids),
            "identity_projection_id": self.identity_projection_id,
            "document_observation_ids": list(self.document_observation_ids),
            "source_document_link_ids": list(self.source_document_link_ids),
            "source_document_descriptor_ids": [
                item.descriptor_id for item in self.source_documents
            ],
            "item_ids": [item.item_id for item in self.items],
            "source_gap_ids": [item.source_gap_id for item in self.source_gaps],
            "limitations": list(self.limitations),
        }

    def validate_identity(self) -> None:
        _CitationDocumentContract.validate_identity(
            actual=self.projection_id,
            prefix="citation-document-projection",
            payload=self.identity_payload(),
            field_name="citation document projection identity",
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentProjectionRequest(DataObjectActionRequest):
    """Complete immutable inputs to one citation/document projection."""

    target_snapshot: CitationTargetSnapshot
    bibliography_bindings: tuple[CitationBibliographyObservationBinding, ...]
    identity_projection: IdentityProjection
    document_observations: tuple[CitationSourceDocumentObservation, ...] = ()
    source_document_link_results: tuple[
        CitationSourceDocumentLinkResult, ...
    ] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        from .linkage import CitationSourceDocumentLinkResult

        if type(self.target_snapshot) is not CitationTargetSnapshot:
            raise TypeError("target_snapshot must be a CitationTargetSnapshot")
        self.target_snapshot.validate_identity()
        if (
            type(self.bibliography_bindings) is not tuple
            or len(self.bibliography_bindings)
            != len(self.target_snapshot.bibliography_entries)
            or any(
                type(item) is not CitationBibliographyObservationBinding
                for item in self.bibliography_bindings
            )
        ):
            raise TypeError("bibliography bindings are invalid")
        for binding in self.bibliography_bindings:
            binding.validate_identity()
        bound_entries = tuple(item.entry for item in self.bibliography_bindings)
        if bound_entries != self.target_snapshot.bibliography_entries:
            raise ValueError(
                "bibliography bindings do not preserve target entry order"
            )
        binding_ids = tuple(
            item.binding_id for item in self.bibliography_bindings
        )
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError(
                "bibliography binding identities contain duplicates"
            )
        if type(self.identity_projection) is not IdentityProjection:
            raise TypeError("identity_projection must be an IdentityProjection")
        replayed = replay_identity_decisions(
            self.identity_projection.candidates,
            self.identity_projection.decisions,
        )
        if replayed != self.identity_projection:
            raise ValueError("identity projection does not match replay")
        if (
            type(self.document_observations) is not tuple
            or len(self.document_observations) > CITATION_DOCUMENT_MAX_KEYS
            or any(
                type(item) is not CitationSourceDocumentObservation
                for item in self.document_observations
            )
        ):
            raise TypeError("document observations are invalid")
        for observation in self.document_observations:
            observation.validate_identity()
        observation_keys = tuple(
            (item.literal_citekey, item.observation_id)
            for item in self.document_observations
        )
        if observation_keys != tuple(sorted(observation_keys)) or len(
            observation_keys
        ) != len(set(observation_keys)):
            raise ValueError("document observations are not canonical")
        target_keys = {item.key for item in self.target_snapshot.groups}
        if any(
            item.target_snapshot_id != self.target_snapshot.snapshot_id
            or item.literal_citekey not in target_keys
            for item in self.document_observations
        ):
            raise ValueError("document observation target conflicts")
        counts_by_key: dict[str, int] = {}
        for observation in self.document_observations:
            counts_by_key[observation.literal_citekey] = (
                counts_by_key.get(observation.literal_citekey, 0) + 1
            )
        if any(
            count > CITATION_DOCUMENT_MAX_OBSERVATIONS_PER_KEY
            for count in counts_by_key.values()
        ):
            raise ValueError("document observations exceed the per-key limit")
        aggregate_documents = sum(
            len(item.source_documents) for item in self.document_observations
        )
        aggregate_inaccessible = sum(
            len(item.inaccessible_evidence_ids)
            for item in self.document_observations
        )
        if (
            aggregate_documents > CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS
            or aggregate_inaccessible
            > CITATION_DOCUMENT_MAX_AGGREGATE_EVIDENCE_IDS
        ):
            raise ValueError("document observation aggregate exceeds the limit")
        if (
            type(self.source_document_link_results) is not tuple
            or len(self.source_document_link_results)
            > CITATION_DOCUMENT_MAX_LINKS
            or any(
                type(item) is not CitationSourceDocumentLinkResult
                for item in self.source_document_link_results
            )
        ):
            raise TypeError("source document link results are invalid")
        for result in self.source_document_link_results:
            result.validate_identity()
        link_ids = tuple(
            item.link.link_id for item in self.source_document_link_results
        )
        if link_ids != tuple(sorted(set(link_ids))):
            raise ValueError("source document link results are not canonical")
        object.__setattr__(
            self,
            "request_id",
            stable_id(
                "citation-document-projection-request",
                self._identity_payload(binding_ids, link_ids),
            ),
        )

    def _identity_payload(
        self,
        binding_ids: tuple[str, ...] | None = None,
        link_ids: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        resolved_bindings = binding_ids or tuple(
            item.binding_id for item in self.bibliography_bindings
        )
        resolved_links = link_ids or tuple(
            item.link.link_id for item in self.source_document_link_results
        )
        return {
            "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
            "target_projection_id": self.target_snapshot.target_projection_id,
            "bibliography_binding_ids": list(sorted(resolved_bindings)),
            "identity_projection_id": self.identity_projection.projection_id,
            "document_observation_ids": [
                item.observation_id for item in self.document_observations
            ],
            "source_document_link_ids": list(resolved_links),
        }

    def validate_identity(self) -> None:
        rebuilt = replace(self)
        if rebuilt != self:
            raise ValueError(
                "citation document projection request does not match replay"
            )
        _CitationDocumentContract.validate_identity(
            actual=self.request_id,
            prefix="citation-document-projection-request",
            payload=self._identity_payload(),
            field_name="citation document projection request identity",
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentProjectionResult(DataObjectActionResult):
    """Bind one request and projector identity to its owner projection."""

    request: CitationDocumentProjectionRequest
    projection: CitationDocumentProjection
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CitationDocumentProjectionRequest:
            raise TypeError(
                "request must be a CitationDocumentProjectionRequest"
            )
        if type(self.projection) is not CitationDocumentProjection:
            raise TypeError("projection must be a CitationDocumentProjection")
        self.request.validate_identity()
        self.projection.validate_identity()
        if self.projection != projection_for(self.request):
            raise ValueError(
                "projection result does not match projector replay"
            )
        object.__setattr__(
            self,
            "result_id",
            stable_id(
                "citation-document-projection-result",
                self._identity_payload(),
            ),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
            "projector": CITATION_DOCUMENT_PROJECTOR_NAME,
            "request_id": self.request.request_id,
            "projection_id": self.projection.projection_id,
        }

    def validate_identity(self) -> None:
        self.request.validate_identity()
        self.projection.validate_identity()
        if self.projection != projection_for(self.request):
            raise ValueError(
                "projection result does not match projector replay"
            )
        _CitationDocumentContract.validate_identity(
            actual=self.result_id,
            prefix="citation-document-projection-result",
            payload=self._identity_payload(),
            field_name="citation document projection result identity",
        )


class _CitationDocumentProjectionBuilder:
    """Build exactly one projection value from a validated request."""

    __slots__ = ()

    def build(
        self,
        request: CitationDocumentProjectionRequest,
    ) -> CitationDocumentProjection:
        if type(request) is not CitationDocumentProjectionRequest:
            raise TypeError(
                "request must be a CitationDocumentProjectionRequest"
            )
        identity_ids_by_key = self._identity_ids_by_key(request)
        all_ids = tuple(
            sorted(
                {
                    identity_id
                    for values in identity_ids_by_key.values()
                    for identity_id in values
                }
            )
        )
        identity_items = self._project_identity_ids(
            request.identity_projection,
            all_ids,
        )
        item_by_identity = {
            item.requested_identity_id: item for item in identity_items
        }
        source_documents = self._source_documents(request.document_observations)
        source_by_id = {
            item.source_document_id: item for item in source_documents
        }
        observations_by_key = self._observations_by_key(
            request.document_observations
        )
        all_links = tuple(
            item.link for item in request.source_document_link_results
        )
        links_by_key = self._links_by_key(all_links)
        items: list[CitationDocumentProjectionItem] = []
        for group in request.target_snapshot.groups:
            ids = identity_ids_by_key[group.key]
            projected = tuple(item_by_identity[item] for item in ids)
            key_status = self._key_status(projected)
            observations = observations_by_key.get(group.key, ())
            group_links = links_by_key.get(group.key, ())
            self._validate_links(
                request=request,
                group=group,
                identity_items=projected,
                observations=observations,
                links=group_links,
                source_by_id=source_by_id,
            )
            document_status = self._document_status(
                key_status=key_status,
                observations=observations,
                links=group_links,
            )
            items.append(
                CitationDocumentProjectionItem(
                    target_snapshot_id=request.target_snapshot.snapshot_id,
                    identity_projection_id=(
                        request.identity_projection.projection_id
                    ),
                    literal_citekey=group.key,
                    occurrence_ids=tuple(
                        request.target_snapshot.occurrences[index].occurrence_id
                        for index in group.occurrence_indexes
                    ),
                    bibliography_membership_status=(
                        CitationBibliographyMembershipStatus.UNDEFINED
                        if group.key in request.target_snapshot.missing_keys
                        else CitationBibliographyMembershipStatus.DEFINED
                    ),
                    key_resolution_status=key_status,
                    identity_items=projected,
                    document_status=document_status,
                    source_document_ids=tuple(
                        sorted(
                            {
                                item.source_document_id
                                for observation in observations
                                for item in observation.source_documents
                            }
                        )
                    ),
                    source_document_link_ids=tuple(
                        sorted(item.link_id for item in group_links)
                    ),
                )
            )
        projection_payload: dict[str, object] = {
            "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
            "target_snapshot_id": request.target_snapshot.snapshot_id,
            "target_projection_id": (
                request.target_snapshot.target_projection_id
            ),
            "bibliography_binding_ids": sorted(
                item.binding_id for item in request.bibliography_bindings
            ),
            "identity_projection_id": request.identity_projection.projection_id,
            "document_observation_ids": sorted(
                item.observation_id for item in request.document_observations
            ),
            "source_document_link_ids": [item.link_id for item in all_links],
            "source_document_descriptor_ids": [
                item.descriptor_id for item in source_documents
            ],
            "item_ids": [item.item_id for item in items],
            "source_gap_ids": [
                item.source_gap_id
                for item in request.target_snapshot.source_gaps
            ],
            "limitations": list(
                CitationDocumentProjection.expected_limitations()
            ),
        }
        projection = CitationDocumentProjection(
            contract_id=CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
            target_snapshot_id=request.target_snapshot.snapshot_id,
            target_projection_id=request.target_snapshot.target_projection_id,
            bibliography_binding_ids=tuple(
                sorted(
                    item.binding_id for item in request.bibliography_bindings
                )
            ),
            identity_projection_id=request.identity_projection.projection_id,
            document_observation_ids=tuple(
                sorted(
                    item.observation_id
                    for item in request.document_observations
                )
            ),
            source_document_link_ids=tuple(item.link_id for item in all_links),
            source_documents=source_documents,
            items=tuple(items),
            source_gaps=request.target_snapshot.source_gaps,
            limitations=CitationDocumentProjection.expected_limitations(),
            projection_id=stable_id(
                "citation-document-projection",
                projection_payload,
            ),
        )
        return projection

    @staticmethod
    def _identity_ids_by_key(
        request: CitationDocumentProjectionRequest,
    ) -> dict[str, tuple[str, ...]]:
        projection = request.identity_projection
        active_ids = set(projection.active_reference_ids)
        accepted_by_key: dict[str, str] = {}
        for name in projection.name_history:
            if not name.active or name.reference_id not in active_ids:
                continue
            if name.canonical_citekey in accepted_by_key:
                raise ValueError("active canonical citekey is ambiguous")
            accepted_by_key[name.canonical_citekey] = name.reference_id
        for alias in projection.alias_history:
            if not alias.active or alias.target_reference_id not in active_ids:
                continue
            existing = accepted_by_key.get(alias.alias_citekey)
            if existing is not None and existing != alias.target_reference_id:
                raise ValueError("active citation alias is ambiguous")
            accepted_by_key[alias.alias_citekey] = alias.target_reference_id
        candidates_by_observation: dict[str, list[str]] = {}
        for candidate in projection.candidates:
            for observation_id in candidate.source_observation_ids:
                candidates_by_observation.setdefault(
                    observation_id,
                    [],
                ).append(candidate.candidate_id)
        bindings_by_key: dict[str, list[str]] = {}
        candidate_by_id = {
            item.candidate_id: item for item in projection.candidates
        }
        for binding in request.bibliography_bindings:
            candidate_ids = candidates_by_observation.get(
                binding.observation.observation_id,
                [],
            )
            for candidate_id in candidate_ids:
                if candidate_by_id[candidate_id].proposed_citekey == (
                    binding.entry.key
                ):
                    bindings_by_key.setdefault(binding.entry.key, []).append(
                        candidate_id
                    )
        result: dict[str, tuple[str, ...]] = {}
        for group in request.target_snapshot.groups:
            accepted = accepted_by_key.get(group.key)
            if accepted is not None:
                result[group.key] = (accepted,)
                continue
            result[group.key] = tuple(
                sorted(set(bindings_by_key.get(group.key, ())))
            )
        return result

    @staticmethod
    def _project_identity_ids(
        projection: IdentityProjection,
        identity_ids: tuple[str, ...],
    ) -> tuple[CitationIdentityProjectionItem, ...]:
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
                    projection=projection,
                    identity_ids=batch,
                )
            )
            values.extend(result.items)
        return tuple(values)

    @staticmethod
    def _key_status(
        items: tuple[CitationIdentityProjectionItem, ...],
    ) -> CitationKeyResolutionStatus:
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

    @staticmethod
    def _source_documents(
        observations: tuple[CitationSourceDocumentObservation, ...],
    ) -> tuple[CitationSourceDocumentDescriptor, ...]:
        by_id: dict[str, CitationSourceDocumentDescriptor] = {}
        for observation in observations:
            for descriptor in observation.source_documents:
                existing = by_id.get(descriptor.source_document_id)
                if existing is not None and existing != descriptor:
                    raise ValueError(
                        "source document identity has conflicting descriptors"
                    )
                by_id[descriptor.source_document_id] = descriptor
        if len(by_id) > CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS:
            raise ValueError("source document count exceeds the limit")
        return tuple(
            sorted(by_id.values(), key=lambda item: item.descriptor_id)
        )

    @staticmethod
    def _observations_by_key(
        observations: tuple[CitationSourceDocumentObservation, ...],
    ) -> dict[str, tuple[CitationSourceDocumentObservation, ...]]:
        grouped: dict[str, list[CitationSourceDocumentObservation]] = {}
        for observation in observations:
            grouped.setdefault(observation.literal_citekey, []).append(
                observation
            )
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    def _links_by_key(
        links: tuple[CitationSourceDocumentLink, ...],
    ) -> dict[str, tuple[CitationSourceDocumentLink, ...]]:
        grouped: dict[str, list[CitationSourceDocumentLink]] = {}
        for link in links:
            grouped.setdefault(link.literal_citekey, []).append(link)
        return {key: tuple(values) for key, values in grouped.items()}

    @staticmethod
    def _validate_links(
        *,
        request: CitationDocumentProjectionRequest,
        group: CitationTargetGroup,
        identity_items: tuple[CitationIdentityProjectionItem, ...],
        observations: tuple[CitationSourceDocumentObservation, ...],
        links: tuple[CitationSourceDocumentLink, ...],
        source_by_id: dict[str, CitationSourceDocumentDescriptor],
    ) -> None:
        identity_by_item = {item.item_id: item for item in identity_items}
        observations_by_id = {
            item.observation_id: item for item in observations
        }
        for link in links:
            if (
                link.target_snapshot_id != request.target_snapshot.snapshot_id
                or link.identity_projection_id
                != request.identity_projection.projection_id
                or link.literal_citekey != group.key
            ):
                raise ValueError("source document link source conflicts")
            identity_item = identity_by_item.get(link.identity_item_id)
            if (
                identity_item is None
                or identity_item.requested_identity_id
                != link.requested_identity_id
            ):
                raise ValueError("source document link identity is stale")
            descriptor = source_by_id.get(
                link.source_document.source_document_id
            )
            if descriptor != link.source_document:
                raise ValueError("source document link descriptor is stale")
            for observation_id in link.availability_observation_ids:
                observation = observations_by_id.get(observation_id)
                if observation is None or descriptor not in (
                    observation.source_documents
                ):
                    raise ValueError(
                        "source document link availability evidence is stale"
                    )

    @staticmethod
    def _document_status(
        *,
        key_status: CitationKeyResolutionStatus,
        observations: tuple[CitationSourceDocumentObservation, ...],
        links: tuple[CitationSourceDocumentLink, ...],
    ) -> CitationDocumentAvailabilityStatus:
        descriptors = {
            item.source_document_id: item
            for observation in observations
            for item in observation.source_documents
        }
        content = {item.content_key for item in descriptors.values()}
        inaccessible = any(
            item.inaccessible_evidence_ids for item in observations
        )
        if links:
            linked_content = {
                item.source_document.content_key for item in links
            }
            if len(linked_content) != 1 or len(content) != 1 or inaccessible:
                return CitationDocumentAvailabilityStatus.AMBIGUOUS
            return CitationDocumentAvailabilityStatus.AVAILABLE_LINKED
        if descriptors:
            if len(content) != 1 or inaccessible:
                return CitationDocumentAvailabilityStatus.AMBIGUOUS
            return (
                CitationDocumentAvailabilityStatus.AVAILABLE_UNVERIFIED_LINKAGE
            )
        if inaccessible:
            return CitationDocumentAvailabilityStatus.INACCESSIBLE
        if key_status is CitationKeyResolutionStatus.RESOLVED and any(
            item.coverage_status == "complete" for item in observations
        ):
            return CitationDocumentAvailabilityStatus.NOT_OBSERVED
        return CitationDocumentAvailabilityStatus.NOT_EVALUATED


def projection_for(
    request: CitationDocumentProjectionRequest,
) -> CitationDocumentProjection:
    """Return the sole canonical projection derived from one request."""
    if type(request) is not CitationDocumentProjectionRequest:
        raise TypeError("request must be a CitationDocumentProjectionRequest")
    return _CitationDocumentProjectionBuilder().build(request)


@final
class CitationDocumentProjector(
    DataObjectActionizer[
        CitationDocumentProjectionRequest,
        CitationDocumentProjectionResult,
    ]
):
    """Correlate exact target keys, identities, and document evidence."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationDocumentProjectionRequest,
    ) -> CitationDocumentProjectionResult:
        if type(self) is not CitationDocumentProjector:
            raise TypeError("projector must be a CitationDocumentProjector")
        return self.project(request=request)

    def project(
        self,
        *,
        request: CitationDocumentProjectionRequest,
    ) -> CitationDocumentProjectionResult:
        if type(self) is not CitationDocumentProjector:
            raise TypeError("projector must be a CitationDocumentProjector")
        if type(request) is not CitationDocumentProjectionRequest:
            raise TypeError(
                "request must be a CitationDocumentProjectionRequest"
            )
        request.validate_identity()
        return CitationDocumentProjectionResult(
            request=request,
            projection=projection_for(request),
        )
