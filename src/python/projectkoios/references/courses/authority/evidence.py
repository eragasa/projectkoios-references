"""References candidate, record, asset, and Ingestion evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum, StrEnum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import validate_citekey

from .errors import CourseReferenceAuthorityError


class ReferenceRecordMatchKind(StrEnum):
    """Classify observed/rendered byte relations without accepting a record."""

    EXACT_OBSERVED_KEY_AND_BYTES = "exact-observed-key-and-bytes"
    EXACT_RENDERED_KEY_AND_BYTES = "exact-rendered-key-and-bytes"
    SAME_KEY_DIFFERENT_BYTES = "same-key-different-bytes"
    SAME_OBSERVED_BYTES_DIFFERENT_KEY = "same-observed-bytes-different-key"
    SAME_RENDERED_BYTES_DIFFERENT_KEY = "same-rendered-bytes-different-key"


class RuntimeAssetAvailability(StrEnum):
    """Represent a fresh path-free runtime availability observation."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedCandidateEntry(DataObjectModel):
    """Expose source observation provenance with no source path."""

    observation_id: str
    source_id: str
    asserted_source_revision: str | None
    bibliography_sha256: str
    bibliography_byte_size: int
    entry_index: int
    observed_citekey: str
    entry_sha256: str
    entry_byte_size: int

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.observation_id, field="observation_id")
        _bounded(self.source_id, field="source_id")
        if self.asserted_source_revision is not None:
            _bounded(
                self.asserted_source_revision,
                field="asserted_source_revision",
            )
        _sha256(self.bibliography_sha256, field="bibliography_sha256")
        if (
            type(self.bibliography_byte_size) is not int
            or self.bibliography_byte_size <= 0
        ):
            raise CourseReferenceAuthorityError(
                "bibliography byte size must be positive"
            )
        if type(self.entry_index) is not int or self.entry_index < 0:
            raise CourseReferenceAuthorityError(
                "entry index must be nonnegative"
            )
        validate_citekey(self.observed_citekey, field="observed citekey")
        _sha256(self.entry_sha256, field="entry_sha256")
        if type(self.entry_byte_size) is not int or self.entry_byte_size <= 0:
            raise CourseReferenceAuthorityError(
                "entry byte size must be positive"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedCandidateEntryEvidence(DataObjectModel):
    """Expose a rendered entry's metadata and identity without its bytes."""

    entry_id: str
    citekey: str
    entry_type: str
    normalized_fields: tuple[tuple[str, str], ...]
    source_observation_ids: tuple[str, ...]
    rendered_sha256: str
    rendered_byte_size: int

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.entry_id, field="entry_id")
        validate_citekey(self.citekey)
        _bounded(self.entry_type, field="entry_type")
        if not isinstance(self.normalized_fields, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or any(type(value) is not str for value in item)
            for item in self.normalized_fields
        ):
            raise TypeError("normalized_fields must be string pairs")
        _content_ids(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        _sha256(self.rendered_sha256, field="rendered_sha256")
        if (
            type(self.rendered_byte_size) is not int
            or self.rendered_byte_size <= 0
        ):
            raise CourseReferenceAuthorityError(
                "rendered entry byte size must be positive"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedEntryCandidateBinding(DataObjectModel):
    """Bind an opaque rendered locator to one exact candidate identity."""

    reference_locator: str
    rendered_entry_id: str
    candidate_id: str
    source_observation_ids: tuple[str, ...]
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.reference_locator, field="reference_locator")
        _content_id(self.rendered_entry_id, field="rendered_entry_id")
        _content_id(self.candidate_id, field="candidate_id")
        _content_ids(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        if self.reference_locator != self.rendered_entry_id:
            raise CourseReferenceAuthorityError(
                "rendered candidate locator differs from its entry identity"
            )
        object.__setattr__(
            self,
            "binding_id",
            _stable_id(
                "rendered-entry-candidate-binding",
                {
                    "candidate_id": self.candidate_id,
                    "reference_locator": self.reference_locator,
                    "rendered_entry_id": self.rendered_entry_id,
                    "source_observation_ids": self.source_observation_ids,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecordDiscrepancy(DataObjectModel):
    """Retain a non-authoritative exact record solely for comparison."""

    citekey: str
    bibtex_entry: str
    authority_status: str = "non-authoritative-discrepancy-observation"
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        validate_citekey(self.citekey)
        _bounded_multiline(
            self.bibtex_entry,
            field="bibtex_entry",
            maximum=262_144,
        )
        if self.authority_status != (
            "non-authoritative-discrepancy-observation"
        ):
            raise CourseReferenceAuthorityError(
                "record discrepancy cannot claim accepted authority"
            )
        object.__setattr__(
            self,
            "record_id",
            _stable_id(
                "reference-record-observation",
                {
                    "authority_status": self.authority_status,
                    "bibtex_entry": self.bibtex_entry,
                    "citekey": self.citekey,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceRecordMatch(DataObjectModel):
    """Describe a discrepancy relation without exposing record bytes."""

    record_id: str
    citekey: str
    bibtex_sha256: str
    bibtex_byte_size: int
    authority_status: str
    kind: ReferenceRecordMatchKind

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.record_id, field="record_id")
        validate_citekey(self.citekey)
        _sha256(self.bibtex_sha256, field="bibtex_sha256")
        if type(self.bibtex_byte_size) is not int or self.bibtex_byte_size <= 0:
            raise CourseReferenceAuthorityError(
                "record byte size must be positive"
            )
        if self.authority_status != (
            "non-authoritative-discrepancy-observation"
        ):
            raise CourseReferenceAuthorityError(
                "record match cannot claim accepted authority"
            )
        if not isinstance(self.kind, ReferenceRecordMatchKind):
            raise TypeError("kind must be a ReferenceRecordMatchKind")


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionArtifactAuthorityLink(DataObjectModel):
    """Bind one asset observation to exact Ingestion cross-binding fields."""

    asset_observation_id: str
    source_id: str
    document_id: str
    artifact_verification_result_id: str
    link_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("asset_observation_id", self.asset_observation_id),
            ("document_id", self.document_id),
            (
                "artifact_verification_result_id",
                self.artifact_verification_result_id,
            ),
        ):
            _content_id(value, field=label)
        _ingestion_identity(self.source_id, field="source_id")
        object.__setattr__(
            self,
            "link_id",
            _stable_id(
                "reference-ingestion-artifact-link",
                {
                    "artifact_verification_result_id": (
                        self.artifact_verification_result_id
                    ),
                    "asset_observation_id": self.asset_observation_id,
                    "document_id": self.document_id,
                    "source_id": self.source_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAssetAuthorityEvidence(DataObjectModel):
    """Expose path-free asset, runtime, document, and ingestion evidence."""

    candidate_id: str
    asset_observation_id: str
    sha256: str
    byte_size: int
    rights_status: str
    asset_status: str
    runtime_availability: RuntimeAssetAvailability
    runtime_evidence_id: str | None = None
    document_binding_ids: tuple[str, ...] = ()
    ingestion_evidence_ids: tuple[str, ...] = ()
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...] = ()

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.candidate_id, field="candidate_id")
        _content_id(
            self.asset_observation_id,
            field="asset_observation_id",
        )
        _sha256(self.sha256, field="asset sha256")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise CourseReferenceAuthorityError(
                "asset byte size must be nonnegative"
            )
        _bounded(self.rights_status, field="rights_status")
        _bounded(self.asset_status, field="asset_status")
        if not isinstance(self.runtime_availability, RuntimeAssetAvailability):
            raise TypeError(
                "runtime_availability must be RuntimeAssetAvailability"
            )
        if self.runtime_availability is RuntimeAssetAvailability.UNKNOWN:
            if self.runtime_evidence_id is not None:
                raise CourseReferenceAuthorityError(
                    "unknown availability cannot cite runtime evidence"
                )
        elif self.runtime_evidence_id is None:
            raise CourseReferenceAuthorityError(
                "known runtime availability requires evidence"
            )
        if self.runtime_evidence_id is not None:
            _content_id(
                self.runtime_evidence_id,
                field="runtime_evidence_id",
            )
        _content_ids(self.document_binding_ids, field="document_binding_ids")
        _content_ids(
            self.ingestion_evidence_ids,
            field="ingestion_evidence_ids",
        )
        if not isinstance(self.ingestion_artifact_links, tuple) or any(
            type(item) is not IngestionArtifactAuthorityLink
            for item in self.ingestion_artifact_links
        ):
            raise TypeError(
                "ingestion_artifact_links must be an exact typed tuple"
            )
        if any(
            item.asset_observation_id != self.asset_observation_id
            for item in self.ingestion_artifact_links
        ):
            raise CourseReferenceAuthorityError(
                "Ingestion artifact link differs from its asset observation"
            )
        if tuple(
            item.link_id for item in self.ingestion_artifact_links
        ) != tuple(
            sorted({item.link_id for item in self.ingestion_artifact_links})
        ):
            raise CourseReferenceAuthorityError(
                "Ingestion artifact links must use unique lexical order"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAssetAuthorityEvidenceRequest(DataObjectActionRequest):
    """Request one path-free authority projection of a source asset."""

    asset: SourceAssetRecord
    runtime_availability: RuntimeAssetAvailability = (
        RuntimeAssetAvailability.UNKNOWN
    )
    runtime_evidence_id: str | None = None
    document_binding_ids: tuple[str, ...] = ()
    ingestion_evidence_ids: tuple[str, ...] = ()
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.asset) is not SourceAssetRecord:
            raise TypeError("asset has an invalid type")
        if not isinstance(self.runtime_availability, RuntimeAssetAvailability):
            raise TypeError("runtime_availability has an invalid type")
        if self.runtime_evidence_id is not None:
            _content_id(
                self.runtime_evidence_id,
                field="runtime_evidence_id",
            )
        _content_ids(self.document_binding_ids, field="document_binding_ids")
        _content_ids(
            self.ingestion_evidence_ids,
            field="ingestion_evidence_ids",
        )
        if not isinstance(self.ingestion_artifact_links, tuple) or any(
            type(item) is not IngestionArtifactAuthorityLink
            for item in self.ingestion_artifact_links
        ):
            raise TypeError(
                "ingestion_artifact_links must be an exact typed tuple"
            )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "reference-asset-authority-evidence-request",
                {
                    "asset": self.asset,
                    "document_binding_ids": self.document_binding_ids,
                    "ingestion_artifact_links": (self.ingestion_artifact_links),
                    "ingestion_evidence_ids": self.ingestion_evidence_ids,
                    "runtime_availability": self.runtime_availability,
                    "runtime_evidence_id": self.runtime_evidence_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceAssetAuthorityEvidenceResult(DataObjectActionResult):
    """Return one path-free source-asset authority projection."""

    request_id: str
    evidence: ReferenceAssetAuthorityEvidence
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.request_id, field="request_id")
        if type(self.evidence) is not ReferenceAssetAuthorityEvidence:
            raise TypeError("evidence has an invalid type")
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "reference-asset-authority-evidence-result",
                {
                    "asset_observation_id": (
                        self.evidence.asset_observation_id
                    ),
                    "request_id": self.request_id,
                    "runtime_evidence_id": (self.evidence.runtime_evidence_id),
                },
            ),
        )


class ReferenceAssetAuthorityEvidenceActionizer(
    DataObjectActionizer[
        ReferenceAssetAuthorityEvidenceRequest,
        ReferenceAssetAuthorityEvidenceResult,
    ]
):
    """Project source-asset state into path-free authority evidence."""

    __slots__ = ()

    def action(
        self,
        *,
        request: ReferenceAssetAuthorityEvidenceRequest,
    ) -> ReferenceAssetAuthorityEvidenceResult:
        """Execute the typed action and return its immutable result.

        Parameters
        ----------
        request
            Typed input governed by the function annotation.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(request) is not ReferenceAssetAuthorityEvidenceRequest:
            raise TypeError("request has an invalid type")
        asset = request.asset
        evidence = ReferenceAssetAuthorityEvidence(
            candidate_id=asset.candidate_id,
            asset_observation_id=_stable_id(
                "catalog-asset-observation",
                asdict(asset),
            ),
            sha256=asset.sha256,
            byte_size=asset.byte_size,
            rights_status=asset.rights_status,
            asset_status=asset.asset_status,
            runtime_availability=request.runtime_availability,
            runtime_evidence_id=request.runtime_evidence_id,
            document_binding_ids=tuple(sorted(request.document_binding_ids)),
            ingestion_evidence_ids=tuple(
                sorted(request.ingestion_evidence_ids)
            ),
            ingestion_artifact_links=tuple(
                sorted(
                    request.ingestion_artifact_links,
                    key=lambda item: item.link_id,
                )
            ),
        )
        return ReferenceAssetAuthorityEvidenceResult(
            request_id=request.request_id,
            evidence=evidence,
        )


_MAX_TEXT = 4_096

_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _bounded(value: str, *, field: str, maximum: int = _MAX_TEXT) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.
    maximum
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CourseReferenceAuthorityError(
            f"{field} must be bounded non-control text"
        )
    return value


def _bounded_multiline(
    value: str,
    *,
    field: str,
    maximum: int,
) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.
    maximum
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(
            ord(character) < 0x20 and character not in "\t\n\r"
            for character in value
        )
    ):
        raise CourseReferenceAuthorityError(
            f"{field} must be bounded multiline text"
        )
    return value


def _content_id(value: str, *, field: str) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if type(value) is not str or _CONTENT_ID.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not a content ID")
    return value


def _content_ids(
    values: tuple[str, ...],
    *,
    field: str,
    ordered: bool = False,
) -> None:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    values
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.
    ordered
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    for value in values:
        _content_id(value, field=field)
    if len(values) != len(set(values)):
        raise CourseReferenceAuthorityError(f"{field} must be unique")
    if not ordered and values != tuple(sorted(values)):
        raise CourseReferenceAuthorityError(f"{field} must use lexical order")


def _ingestion_identity(value: str, *, field: str) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if type(value) is not str or not value:
        raise CourseReferenceAuthorityError(
            f"{field} must be a nonempty Ingestion identity"
        )
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise CourseReferenceAuthorityError(
            f"{field} must be valid UTF-8"
        ) from error
    if len(encoded) > 1_024:
        raise CourseReferenceAuthorityError(
            f"{field} exceeds the Ingestion identity limit"
        )
    return value


def _sha256(value: str, *, field: str) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.
    field
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(f"{field} is not SHA-256")
    return value


def _stable_id(kind: str, payload: object) -> str:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    kind
        Typed input governed by the function annotation.
    payload
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    encoded = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_default(value: object) -> object:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    value
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: getattr(value, item.name)
            for item in value.__dataclass_fields__.values()
            if item.init
        }
    raise TypeError(f"unsupported identity value: {type(value).__name__}")
