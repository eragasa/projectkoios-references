from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.path_safety import validate_citekey

from ._contract import (
    CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY,
    CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
    CITATION_SOURCE_DOCUMENT_LINKER_NAME,
    _CitationDocumentContract,
    stable_id,
)
from .document import CitationSourceDocumentDescriptor
from .statuses import (
    CitationDocumentAvailabilityStatus,
    CitationKeyResolutionStatus,
)

if TYPE_CHECKING:
    from .projection import (
        CitationDocumentProjectionItem,
        CitationDocumentProjectionResult,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentLink(DataObjectModel):
    """Neutral exact linkage; it grants no rights, use, or review authority."""

    creating_request_id: str
    prior_projection_id: str
    prior_item_id: str
    target_snapshot_id: str
    identity_projection_id: str
    literal_citekey: str
    identity_item_id: str
    requested_identity_id: str
    source_document: CitationSourceDocumentDescriptor
    availability_observation_ids: tuple[str, ...]
    pre_effect_intent_id: str
    linkage_basis: str
    limitations: tuple[str, ...]
    link_id: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.creating_request_id, "link creating request identity"),
            (self.prior_projection_id, "prior projection identity"),
            (self.prior_item_id, "prior projection item identity"),
            (self.identity_projection_id, "identity projection identity"),
            (self.identity_item_id, "identity projection item identity"),
            (self.requested_identity_id, "requested bibliographic identity"),
            (self.pre_effect_intent_id, "pre-effect intent identity"),
        ):
            _CitationDocumentContract.opaque_id(value, field_name=field_name)
        _CitationDocumentContract.target_id(
            self.target_snapshot_id,
            kind="snapshot",
            field_name="link target snapshot identity",
        )
        validate_citekey(self.literal_citekey, field="linked literal key")
        if not isinstance(
            self.source_document,
            CitationSourceDocumentDescriptor,
        ):
            raise TypeError(
                "source_document must be a CitationSourceDocumentDescriptor"
            )
        if (
            not isinstance(self.availability_observation_ids, tuple)
            or not self.availability_observation_ids
            or len(self.availability_observation_ids)
            > CITATION_DOCUMENT_MAX_EVIDENCE_IDS_PER_KEY
            or self.availability_observation_ids
            != tuple(sorted(set(self.availability_observation_ids)))
        ):
            raise ValueError(
                "availability observation identities are not canonical"
            )
        for identity in self.availability_observation_ids:
            _CitationDocumentContract.opaque_id(
                identity,
                field_name="availability observation identity",
            )
        if self.linkage_basis != "explicit-upload-for-requested-citation":
            raise ValueError(
                "citation source-document linkage basis is invalid"
            )
        if self.limitations != self.expected_limitations():
            raise ValueError("citation source-document limitations are invalid")
        self.validate_identity()

    @staticmethod
    def expected_limitations() -> tuple[str, ...]:
        return (
            "not-canonical-asset-authorization",
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
            "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
            "creating_request_id": self.creating_request_id,
            "prior_projection_id": self.prior_projection_id,
            "prior_item_id": self.prior_item_id,
            "target_snapshot_id": self.target_snapshot_id,
            "identity_projection_id": self.identity_projection_id,
            "literal_citekey": self.literal_citekey,
            "identity_item_id": self.identity_item_id,
            "requested_identity_id": self.requested_identity_id,
            "source_document": self.source_document.record_payload(),
            "availability_observation_ids": list(
                self.availability_observation_ids
            ),
            "pre_effect_intent_id": self.pre_effect_intent_id,
            "linkage_basis": self.linkage_basis,
            "limitations": list(self.limitations),
        }

    def validate_identity(self) -> None:
        _CitationDocumentContract.validate_identity(
            actual=self.link_id,
            prefix="citation-source-document-link",
            payload=self.identity_payload(),
            field_name="citation source-document link identity",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentLinkRequest(DataObjectActionRequest):
    """Request one neutral link from an exact available projection item."""

    projection_result: CitationDocumentProjectionResult
    item_id: str
    identity_item_id: str
    source_document_id: str
    pre_effect_intent_id: str
    linkage_basis: str = "explicit-upload-for-requested-citation"
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        from .projection import CitationDocumentProjectionResult

        if type(self.projection_result) is not CitationDocumentProjectionResult:
            raise TypeError(
                "projection_result must be a CitationDocumentProjectionResult"
            )
        self.projection_result.validate_identity()
        for value, field_name in (
            (self.item_id, "link projection item identity"),
            (self.identity_item_id, "link identity item identity"),
            (self.source_document_id, "link source document identity"),
            (self.pre_effect_intent_id, "link pre-effect intent identity"),
        ):
            _CitationDocumentContract.opaque_id(value, field_name=field_name)
        if self.linkage_basis != "explicit-upload-for-requested-citation":
            raise ValueError("source document linkage basis is invalid")
        item = self.selected_item()
        if (
            item.key_resolution_status
            is not CitationKeyResolutionStatus.RESOLVED
        ):
            raise ValueError("source document link requires resolved identity")
        if self.identity_item_id != item.identity_items[0].item_id:
            raise ValueError("source document link identity item conflicts")
        if self.source_document_id not in item.source_document_ids:
            raise ValueError("source document is unavailable for this key")
        if item.document_status not in {
            CitationDocumentAvailabilityStatus.AVAILABLE_UNVERIFIED_LINKAGE,
            CitationDocumentAvailabilityStatus.AVAILABLE_LINKED,
        }:
            raise ValueError("projection item is not linkable")
        object.__setattr__(
            self,
            "request_id",
            stable_id(
                "citation-source-document-link-request",
                self._identity_payload(),
            ),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
            "projection_result_id": self.projection_result.result_id,
            "item_id": self.item_id,
            "identity_item_id": self.identity_item_id,
            "source_document_id": self.source_document_id,
            "pre_effect_intent_id": self.pre_effect_intent_id,
            "linkage_basis": self.linkage_basis,
        }

    def validate_identity(self) -> None:
        rebuilt = replace(self)
        if rebuilt != self:
            raise ValueError(
                "citation source-document link request does not match replay"
            )
        _CitationDocumentContract.validate_identity(
            actual=self.request_id,
            prefix="citation-source-document-link-request",
            payload=self._identity_payload(),
            field_name="citation source-document link request identity",
        )

    def selected_item(self) -> CitationDocumentProjectionItem:
        matches = tuple(
            item
            for item in self.projection_result.projection.items
            if item.item_id == self.item_id
        )
        if len(matches) != 1:
            raise ValueError("link projection item is absent or ambiguous")
        return matches[0]


def link_for(
    request: CitationSourceDocumentLinkRequest,
) -> CitationSourceDocumentLink:
    """Return the sole canonical neutral link derived from one request."""
    if type(request) is not CitationSourceDocumentLinkRequest:
        raise TypeError("request must be a CitationSourceDocumentLinkRequest")
    projection = request.projection_result.projection
    item = request.selected_item()
    identity_item = item.identity_items[0]
    descriptor = next(
        value
        for value in projection.source_documents
        if value.source_document_id == request.source_document_id
    )
    observations = tuple(
        value.observation_id
        for value in request.projection_result.request.document_observations
        if value.literal_citekey == item.literal_citekey
        and any(candidate == descriptor for candidate in value.source_documents)
    )
    if not observations:
        raise ValueError("source document has no availability observation")
    identity_payload: dict[str, object] = {
        "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
        "creating_request_id": request.request_id,
        "prior_projection_id": projection.projection_id,
        "prior_item_id": item.item_id,
        "target_snapshot_id": projection.target_snapshot_id,
        "identity_projection_id": projection.identity_projection_id,
        "literal_citekey": item.literal_citekey,
        "identity_item_id": identity_item.item_id,
        "requested_identity_id": identity_item.requested_identity_id,
        "source_document": descriptor.record_payload(),
        "availability_observation_ids": list(sorted(observations)),
        "pre_effect_intent_id": request.pre_effect_intent_id,
        "linkage_basis": request.linkage_basis,
        "limitations": list(CitationSourceDocumentLink.expected_limitations()),
    }
    return CitationSourceDocumentLink(
        creating_request_id=request.request_id,
        prior_projection_id=projection.projection_id,
        prior_item_id=item.item_id,
        target_snapshot_id=projection.target_snapshot_id,
        identity_projection_id=projection.identity_projection_id,
        literal_citekey=item.literal_citekey,
        identity_item_id=identity_item.item_id,
        requested_identity_id=identity_item.requested_identity_id,
        source_document=descriptor,
        availability_observation_ids=tuple(sorted(observations)),
        pre_effect_intent_id=request.pre_effect_intent_id,
        linkage_basis=request.linkage_basis,
        limitations=CitationSourceDocumentLink.expected_limitations(),
        link_id=stable_id(
            "citation-source-document-link",
            identity_payload,
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentLinkResult(DataObjectActionResult):
    """Bind one exact link request to its neutral immutable link."""

    request: CitationSourceDocumentLinkRequest
    link: CitationSourceDocumentLink
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CitationSourceDocumentLinkRequest:
            raise TypeError(
                "request must be a CitationSourceDocumentLinkRequest"
            )
        if type(self.link) is not CitationSourceDocumentLink:
            raise TypeError("link must be a CitationSourceDocumentLink")
        self.request.validate_identity()
        self.link.validate_identity()
        if self.link != link_for(self.request):
            raise ValueError(
                "source document link does not match linker replay"
            )
        object.__setattr__(
            self,
            "result_id",
            stable_id(
                "citation-source-document-link-result",
                self._identity_payload(),
            ),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
            "linker": CITATION_SOURCE_DOCUMENT_LINKER_NAME,
            "request_id": self.request.request_id,
            "link_id": self.link.link_id,
        }

    def validate_identity(self) -> None:
        self.request.validate_identity()
        self.link.validate_identity()
        if self.link != link_for(self.request):
            raise ValueError(
                "source document link does not match linker replay"
            )
        _CitationDocumentContract.validate_identity(
            actual=self.result_id,
            prefix="citation-source-document-link-result",
            payload=self._identity_payload(),
            field_name="citation source-document link result identity",
        )


class CitationSourceDocumentLinker(
    DataObjectActionizer[
        CitationSourceDocumentLinkRequest,
        CitationSourceDocumentLinkResult,
    ]
):
    """Create a neutral exact link without granting protected authority."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationSourceDocumentLinkRequest,
    ) -> CitationSourceDocumentLinkResult:
        return self.link(request=request)

    def link(
        self,
        *,
        request: CitationSourceDocumentLinkRequest,
    ) -> CitationSourceDocumentLinkResult:
        if type(request) is not CitationSourceDocumentLinkRequest:
            raise TypeError(
                "request must be a CitationSourceDocumentLinkRequest"
            )
        request.validate_identity()
        return CitationSourceDocumentLinkResult(
            request=request,
            link=link_for(request),
        )
