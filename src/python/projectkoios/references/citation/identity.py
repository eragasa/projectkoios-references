from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.identity import (
    AcceptedReference,
    IdentityProjection,
    ReferenceCandidate,
    replay_identity_decisions,
)
from projectkoios.references.path_safety import validate_citekey

CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES = 1_024
CITATION_IDENTITY_PROJECTION_MAX_ID_BYTES = 512


class CitationIdentityProjectionStatus(StrEnum):
    """Closed citation-identity outcomes without use or support authority."""

    ACCEPTED_ACTIVE_CANONICAL = "accepted-active-canonical"
    ACCEPTED_WITHOUT_ACTIVE_CITEKEY = "accepted-without-active-citekey"
    CANDIDATE_PROPOSED_NONCANONICAL = "candidate-proposed-noncanonical"
    INACTIVE_SUPERSEDED = "inactive-superseded"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationIdentityProjectionRequest(DataObjectActionRequest):
    """Request citation-safe views of bounded opaque identity IDs."""

    projection: IdentityProjection
    identity_ids: tuple[str, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.projection) is not IdentityProjection:
            raise TypeError("projection must be an IdentityProjection")
        replayed = replay_identity_decisions(
            self.projection.candidates,
            self.projection.decisions,
        )
        if replayed != self.projection:
            raise ValueError("identity projection does not match replay")
        if not isinstance(self.identity_ids, tuple) or any(
            not isinstance(identity_id, str)
            for identity_id in self.identity_ids
        ):
            raise TypeError("identity_ids must be a string tuple")
        if not self.identity_ids:
            raise ValueError("identity_ids must be non-empty")
        if len(self.identity_ids) > CITATION_IDENTITY_PROJECTION_MAX_IDENTITIES:
            raise ValueError("citation identity request exceeds the item limit")
        for identity_id in self.identity_ids:
            self._validate_identity_id(identity_id)
        if len(set(self.identity_ids)) != len(self.identity_ids):
            raise ValueError("identity_ids contain duplicates")
        if self.identity_ids != tuple(sorted(self.identity_ids)):
            raise ValueError("identity_ids must use canonical sorted order")
        object.__setattr__(
            self,
            "request_id",
            self.identity_for(
                projection_id=self.projection.projection_id,
                identity_ids=self.identity_ids,
            ),
        )

    @staticmethod
    def _validate_identity_id(identity_id: str) -> None:
        if len(identity_id) > CITATION_IDENTITY_PROJECTION_MAX_ID_BYTES:
            raise ValueError("bibliographic identity ID is malformed")
        try:
            encoded = identity_id.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(
                "bibliographic identity ID is malformed"
            ) from error
        if (
            not identity_id
            or identity_id != identity_id.strip()
            or len(encoded) > CITATION_IDENTITY_PROJECTION_MAX_ID_BYTES
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in identity_id
            )
        ):
            raise ValueError("bibliographic identity ID is malformed")

    @staticmethod
    def identity_for(
        *,
        projection_id: str,
        identity_ids: tuple[str, ...],
    ) -> str:
        canonical = json.dumps(
            {
                "identity_ids": identity_ids,
                "projection_id": projection_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-identity-projection-request:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationIdentityProjectionItem(DataObjectModel):
    """One citation-safe identity outcome correlated to the requested ID."""

    requested_identity_id: str
    projection_id: str
    status: CitationIdentityProjectionStatus
    reference_id: str | None = None
    canonical_citekey: str | None = None
    proposed_citekey: str | None = None
    successor_reference_ids: tuple[str, ...] = ()
    item_id: str = field(init=False)

    def __post_init__(self) -> None:
        CitationIdentityProjectionRequest._validate_identity_id(
            self.requested_identity_id
        )
        CitationIdentityProjectionRequest._validate_identity_id(
            self.projection_id
        )
        if not isinstance(self.status, CitationIdentityProjectionStatus):
            raise TypeError("status must be a CitationIdentityProjectionStatus")
        if not isinstance(self.successor_reference_ids, tuple) or any(
            not isinstance(identity_id, str)
            for identity_id in self.successor_reference_ids
        ):
            raise TypeError("successor_reference_ids must be a string tuple")
        for identity_id in self.successor_reference_ids:
            CitationIdentityProjectionRequest._validate_identity_id(identity_id)
        if self.successor_reference_ids != tuple(
            sorted(set(self.successor_reference_ids))
        ):
            raise ValueError(
                "successor_reference_ids must be unique canonical order"
            )
        self._validate_status_fields()
        object.__setattr__(
            self,
            "item_id",
            self.identity_for(
                requested_identity_id=self.requested_identity_id,
                projection_id=self.projection_id,
                status=self.status,
                reference_id=self.reference_id,
                canonical_citekey=self.canonical_citekey,
                proposed_citekey=self.proposed_citekey,
                successor_reference_ids=self.successor_reference_ids,
            ),
        )

    def _validate_status_fields(self) -> None:
        accepted = {
            CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL,
            CitationIdentityProjectionStatus.ACCEPTED_WITHOUT_ACTIVE_CITEKEY,
            CitationIdentityProjectionStatus.INACTIVE_SUPERSEDED,
        }
        if self.status in accepted:
            if self.reference_id != self.requested_identity_id:
                raise ValueError(
                    "accepted identity outcome must retain its reference ID"
                )
        elif self.reference_id is not None:
            raise ValueError(
                "candidate and unresolved outcomes cannot claim a reference ID"
            )

        if self.status is (
            CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL
        ):
            if (
                self.canonical_citekey is None
                or self.proposed_citekey is not None
                or self.successor_reference_ids
            ):
                raise ValueError("active accepted outcome fields are invalid")
            validate_citekey(
                self.canonical_citekey,
                field="canonical_citekey",
            )
        elif self.status is (
            CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
        ):
            if (
                self.proposed_citekey is None
                or self.canonical_citekey is not None
                or self.successor_reference_ids
            ):
                raise ValueError("candidate outcome fields are invalid")
            validate_citekey(
                self.proposed_citekey,
                field="proposed_citekey",
            )
        elif (
            self.status is CitationIdentityProjectionStatus.INACTIVE_SUPERSEDED
        ):
            if (
                not self.successor_reference_ids
                or self.canonical_citekey is not None
                or self.proposed_citekey is not None
            ):
                raise ValueError("superseded outcome fields are invalid")
        elif (
            self.canonical_citekey is not None
            or self.proposed_citekey is not None
            or self.successor_reference_ids
        ):
            raise ValueError("non-key outcome fields are invalid")

    @staticmethod
    def identity_for(
        *,
        requested_identity_id: str,
        projection_id: str,
        status: CitationIdentityProjectionStatus,
        reference_id: str | None,
        canonical_citekey: str | None,
        proposed_citekey: str | None,
        successor_reference_ids: tuple[str, ...],
    ) -> str:
        canonical = json.dumps(
            {
                "canonical_citekey": canonical_citekey,
                "projection_id": projection_id,
                "proposed_citekey": proposed_citekey,
                "reference_id": reference_id,
                "requested_identity_id": requested_identity_id,
                "status": status.value,
                "successor_reference_ids": successor_reference_ids,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-identity-projection-item:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationIdentityProjectionResult(DataObjectActionResult):
    """Bind one request to ordered, correlated citation-identity outcomes."""

    request: CitationIdentityProjectionRequest
    items: tuple[CitationIdentityProjectionItem, ...]
    projection_id: str = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CitationIdentityProjectionRequest:
            raise TypeError(
                "request must be a CitationIdentityProjectionRequest"
            )
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, CitationIdentityProjectionItem)
            for item in self.items
        ):
            raise TypeError(
                "items must be a CitationIdentityProjectionItem tuple"
            )
        if tuple(item.requested_identity_id for item in self.items) != (
            self.request.identity_ids
        ):
            raise ValueError("items do not preserve request correlation")
        projection_id = self.request.projection.projection_id
        if any(item.projection_id != projection_id for item in self.items):
            raise ValueError("item projection identity does not match request")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("item identities contain duplicates")
        object.__setattr__(self, "projection_id", projection_id)
        object.__setattr__(
            self,
            "result_id",
            self.identity_for(
                request_id=self.request.request_id,
                projection_id=projection_id,
                item_ids=tuple(item.item_id for item in self.items),
            ),
        )

    @staticmethod
    def identity_for(
        *,
        request_id: str,
        projection_id: str,
        item_ids: tuple[str, ...],
    ) -> str:
        canonical = json.dumps(
            {
                "item_ids": item_ids,
                "projection_id": projection_id,
                "request_id": request_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "citation-identity-projection-result:sha256:"
            + hashlib.sha256(canonical).hexdigest()
        )


class CitationIdentityProjector(
    DataObjectActionizer[
        CitationIdentityProjectionRequest,
        CitationIdentityProjectionResult,
    ]
):
    """Project citation-safe identity status without granting use authority."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationIdentityProjectionRequest,
    ) -> CitationIdentityProjectionResult:
        return self.project(request=request)

    def project(
        self,
        *,
        request: CitationIdentityProjectionRequest,
    ) -> CitationIdentityProjectionResult:
        if type(request) is not CitationIdentityProjectionRequest:
            raise TypeError(
                "request must be a CitationIdentityProjectionRequest"
            )
        projection = request.projection
        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in projection.candidates
        }
        if len(candidate_by_id) != len(projection.candidates):
            raise ValueError("identity projection has ambiguous candidates")
        reference_by_id = {
            reference.reference_id: reference
            for reference in projection.accepted_references
        }
        if len(reference_by_id) != len(projection.accepted_references):
            raise ValueError("identity projection has ambiguous references")
        if set(candidate_by_id) & set(reference_by_id):
            raise ValueError("identity projection has ambiguous identity kinds")

        active_reference_ids = set(projection.active_reference_ids)
        if not active_reference_ids <= set(reference_by_id):
            raise ValueError(
                "identity projection has unknown active references"
            )

        active_name_by_reference: dict[str, str] = {}
        for binding in projection.name_history:
            if binding.reference_id not in reference_by_id:
                raise ValueError(
                    "identity projection name has unknown reference"
                )
            if not binding.active:
                continue
            if binding.reference_id not in active_reference_ids:
                raise ValueError("inactive reference has an active citekey")
            if binding.reference_id in active_name_by_reference:
                raise ValueError(
                    "identity projection has ambiguous active citekeys"
                )
            active_name_by_reference[binding.reference_id] = (
                binding.canonical_citekey
            )

        successor_by_reference: dict[str, tuple[str, ...]] = {}
        for supersession in projection.supersessions:
            source_id = supersession.source_reference_id
            if source_id not in reference_by_id or any(
                target_id not in reference_by_id
                for target_id in supersession.target_reference_ids
            ):
                raise ValueError(
                    "identity projection supersession has unknown references"
                )
            if source_id in successor_by_reference:
                raise ValueError(
                    "identity projection has ambiguous supersession"
                )
            successor_by_reference[source_id] = tuple(
                sorted(supersession.target_reference_ids)
            )
        if active_reference_ids & set(successor_by_reference):
            raise ValueError("active reference cannot also be superseded")

        items = tuple(
            self._project_identity(
                identity_id=identity_id,
                projection_id=projection.projection_id,
                candidate_by_id=candidate_by_id,
                reference_by_id=reference_by_id,
                active_reference_ids=active_reference_ids,
                active_name_by_reference=active_name_by_reference,
                successor_by_reference=successor_by_reference,
            )
            for identity_id in request.identity_ids
        )
        return CitationIdentityProjectionResult(request=request, items=items)

    @staticmethod
    def _project_identity(
        *,
        identity_id: str,
        projection_id: str,
        candidate_by_id: dict[str, ReferenceCandidate],
        reference_by_id: dict[str, AcceptedReference],
        active_reference_ids: set[str],
        active_name_by_reference: dict[str, str],
        successor_by_reference: dict[str, tuple[str, ...]],
    ) -> CitationIdentityProjectionItem:
        if identity_id in candidate_by_id:
            candidate = candidate_by_id[identity_id]
            return CitationIdentityProjectionItem(
                requested_identity_id=identity_id,
                projection_id=projection_id,
                status=(
                    CitationIdentityProjectionStatus.CANDIDATE_PROPOSED_NONCANONICAL
                ),
                proposed_citekey=candidate.proposed_citekey,
            )
        if identity_id in reference_by_id:
            if identity_id in successor_by_reference:
                return CitationIdentityProjectionItem(
                    requested_identity_id=identity_id,
                    projection_id=projection_id,
                    status=(
                        CitationIdentityProjectionStatus.INACTIVE_SUPERSEDED
                    ),
                    reference_id=identity_id,
                    successor_reference_ids=successor_by_reference[identity_id],
                )
            canonical_citekey = active_name_by_reference.get(identity_id)
            if (
                identity_id in active_reference_ids
                and canonical_citekey is not None
            ):
                return CitationIdentityProjectionItem(
                    requested_identity_id=identity_id,
                    projection_id=projection_id,
                    status=(
                        CitationIdentityProjectionStatus.ACCEPTED_ACTIVE_CANONICAL
                    ),
                    reference_id=identity_id,
                    canonical_citekey=canonical_citekey,
                )
            return CitationIdentityProjectionItem(
                requested_identity_id=identity_id,
                projection_id=projection_id,
                status=(
                    CitationIdentityProjectionStatus.ACCEPTED_WITHOUT_ACTIVE_CITEKEY
                ),
                reference_id=identity_id,
            )
        return CitationIdentityProjectionItem(
            requested_identity_id=identity_id,
            projection_id=projection_id,
            status=CitationIdentityProjectionStatus.UNRESOLVED,
        )
