"""Replay-current Search authority projection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Protocol, cast, runtime_checkable

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.path_safety import validate_citekey
from projectkoios.references.review import (
    CanonicalAssetDecision,
    HumanReviewDimension,
    ReferenceIdentityDecision,
    ReviewProjection,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
)

from .authority_state import ActiveReferenceAuthority
from .contract import COURSE_REFERENCE_AUTHORITY_CONTRACT_ID
from .errors import CourseReferenceAuthorityError
from .evidence import (
    IngestionArtifactAuthorityLink,
    ReferenceAssetAuthorityEvidence,
    RuntimeAssetAvailability,
)


class SearchReferenceAuthorityProjectionReadError(RuntimeError):
    """Report path-free failure to obtain persisted projection bytes."""

    code = "search-reference-authority-projection-unavailable"

    def __init__(self) -> None:
        """Create the sole deterministic public failure projection."""
        super().__init__("Search reference authority projection is unavailable")


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityBinding(DataObjectModel):
    """Supply the exact References C authority needed by Search."""

    candidate_id: str
    bibliographic_work_id: str
    reference_identity_status: str
    accepted_citekey: str
    source_asset_id: str
    authority_binding_id: str
    identity_decision_id: str
    canonical_asset_decision_id: str
    ingestion_artifact_links: tuple[IngestionArtifactAuthorityLink, ...]
    authority_evidence_ids: tuple[str, ...]
    state_projection_id: str
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        for label, value in (
            ("candidate_id", self.candidate_id),
            ("bibliographic_work_id", self.bibliographic_work_id),
            ("source_asset_id", self.source_asset_id),
            ("authority_binding_id", self.authority_binding_id),
            ("identity_decision_id", self.identity_decision_id),
            (
                "canonical_asset_decision_id",
                self.canonical_asset_decision_id,
            ),
            ("state_projection_id", self.state_projection_id),
        ):
            _content_id(value, field=label)
        if self.reference_identity_status != "accepted":
            raise CourseReferenceAuthorityError(
                "Search authority binding must be explicitly accepted"
            )
        if not isinstance(self.ingestion_artifact_links, tuple) or any(
            type(item) is not IngestionArtifactAuthorityLink
            for item in self.ingestion_artifact_links
        ):
            raise TypeError(
                "ingestion_artifact_links must be an exact typed tuple"
            )
        if not self.ingestion_artifact_links:
            raise CourseReferenceAuthorityError(
                "ingestion_artifact_links must be non-empty"
            )
        if tuple(
            item.link_id for item in self.ingestion_artifact_links
        ) != tuple(
            sorted({item.link_id for item in self.ingestion_artifact_links})
        ):
            raise CourseReferenceAuthorityError(
                "Search Ingestion links must use unique lexical order"
            )
        _content_ids(
            self.authority_evidence_ids,
            field="authority_evidence_ids",
        )
        validate_citekey(self.accepted_citekey, field="accepted citekey")
        object.__setattr__(
            self,
            "binding_id",
            _stable_id(
                "search-reference-authority-binding",
                {
                    "accepted_citekey": self.accepted_citekey,
                    "authority_binding_id": self.authority_binding_id,
                    "authority_evidence_ids": self.authority_evidence_ids,
                    "bibliographic_work_id": self.bibliographic_work_id,
                    "candidate_id": self.candidate_id,
                    "canonical_asset_decision_id": (
                        self.canonical_asset_decision_id
                    ),
                    "identity_decision_id": self.identity_decision_id,
                    "ingestion_artifact_links": self.ingestion_artifact_links,
                    "reference_identity_status": (
                        self.reference_identity_status
                    ),
                    "source_asset_id": self.source_asset_id,
                    "state_projection_id": self.state_projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjection(DataObjectActionResult):
    """Return only replay-current complete authority bindings for Search."""

    review_projection_id: str
    bindings: tuple[SearchReferenceAuthorityBinding, ...]
    projection_id: str = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        _content_id(self.review_projection_id, field="review_projection_id")
        if not isinstance(self.bindings, tuple) or any(
            type(item) is not SearchReferenceAuthorityBinding
            for item in self.bindings
        ):
            raise TypeError("bindings must be an exact typed tuple")
        binding_ids = tuple(item.binding_id for item in self.bindings)
        if binding_ids != tuple(sorted(set(binding_ids))):
            raise CourseReferenceAuthorityError(
                "Search authority bindings must use unique canonical order"
            )
        projection_id = _stable_id(
            "search-reference-authority-projection",
            {
                "binding_ids": tuple(item.binding_id for item in self.bindings),
                "review_projection_id": self.review_projection_id,
            },
        )
        object.__setattr__(self, "projection_id", projection_id)
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "search-reference-authority-result",
                {
                    "contract_id": COURSE_REFERENCE_AUTHORITY_CONTRACT_ID,
                    "projection_id": projection_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjectionRequest(DataObjectActionRequest):
    """Request replay-current accepted Search reference authority."""

    review_projection: ReviewProjection
    state_projections: tuple[ReferenceStateProjection, ...]
    asset_evidence: tuple[ReferenceAssetAuthorityEvidence, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object.

        Returns
        -------
        object
            Immutable typed output governed by the return annotation.

        """
        if type(self.review_projection) is not ReviewProjection:
            raise TypeError("review_projection has an invalid type")
        if not isinstance(self.state_projections, tuple) or any(
            type(item) is not ReferenceStateProjection
            for item in self.state_projections
        ):
            raise TypeError("state_projections must be an exact typed tuple")
        if not isinstance(self.asset_evidence, tuple) or any(
            type(item) is not ReferenceAssetAuthorityEvidence
            for item in self.asset_evidence
        ):
            raise TypeError("asset_evidence must be an exact typed tuple")
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "search-reference-authority-projection-request",
                {
                    "asset_observation_ids": tuple(
                        item.asset_observation_id
                        for item in self.asset_evidence
                    ),
                    "review_projection_id": (
                        self.review_projection.projection_id
                    ),
                    "state_projection_ids": tuple(
                        item.projection_id for item in self.state_projections
                    ),
                },
            ),
        )


class SearchReferenceAuthorityProjectionActionizer(
    DataObjectActionizer[
        SearchReferenceAuthorityProjectionRequest,
        SearchReferenceAuthorityProjection,
    ]
):
    """Project only complete authority with typed Ingestion linkage."""

    __slots__ = ()

    def action(
        self,
        *,
        request: SearchReferenceAuthorityProjectionRequest,
    ) -> SearchReferenceAuthorityProjection:
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
        if type(request) is not SearchReferenceAuthorityProjectionRequest:
            raise TypeError("request has an invalid type")
        active = _active_authorities(
            request.state_projections,
            request.review_projection,
        )
        projections_by_id = {
            item.projection_id: item for item in request.state_projections
        }
        bindings = []
        for item in active:
            if (
                item.source_asset_id is None
                or item.canonical_asset_decision_id is None
                or item.authority_binding_id is None
            ):
                continue
            matching_assets = tuple(
                asset
                for asset in request.asset_evidence
                if asset.candidate_id == item.candidate_id
                and item.source_asset_id
                == _stable_id(
                    "source-asset",
                    {
                        "asset_observation_id": asset.asset_observation_id,
                        "authorization_decision_id": (
                            item.canonical_asset_decision_id
                        ),
                        "bibliographic_work_id": item.bibliographic_work_id,
                    },
                )
            )
            if (
                len(matching_assets) != 1
                or not matching_assets[0].ingestion_artifact_links
            ):
                continue
            selected = matching_assets[0]
            authoritative_inputs = set(
                projections_by_id[
                    item.state_projection_id
                ].authoritative_input_ids
            )
            if (
                selected.runtime_availability
                is not RuntimeAssetAvailability.AVAILABLE
                or not set(_asset_evidence_ids(selected)).issubset(
                    authoritative_inputs
                )
                or any(
                    link.link_id not in authoritative_inputs
                    for link in selected.ingestion_artifact_links
                )
            ):
                continue
            bindings.append(
                SearchReferenceAuthorityBinding(
                    candidate_id=item.candidate_id,
                    bibliographic_work_id=item.bibliographic_work_id,
                    reference_identity_status="accepted",
                    accepted_citekey=item.active_citekey,
                    source_asset_id=item.source_asset_id,
                    authority_binding_id=item.authority_binding_id,
                    identity_decision_id=item.identity_decision_id,
                    canonical_asset_decision_id=(
                        item.canonical_asset_decision_id
                    ),
                    ingestion_artifact_links=(
                        selected.ingestion_artifact_links
                    ),
                    authority_evidence_ids=projections_by_id[
                        item.state_projection_id
                    ].authoritative_input_ids,
                    state_projection_id=item.state_projection_id,
                )
            )
        return SearchReferenceAuthorityProjection(
            review_projection_id=request.review_projection.projection_id,
            bindings=tuple(sorted(bindings, key=lambda item: item.binding_id)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjectionReadRequest(DataObjectActionRequest):
    """Request one exact persisted Search authority projection."""

    expected_sha256: str
    expected_byte_size: int
    expected_projection_id: str
    expected_projection_result_id: str
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object."""
        _sha256(self.expected_sha256, field="expected_sha256")
        if (
            type(self.expected_byte_size) is not int
            or self.expected_byte_size <= 0
            or self.expected_byte_size > _MAX_SEARCH_AUTHORITY_PROJECTION_BYTES
        ):
            raise CourseReferenceAuthorityError(
                "expected_byte_size must be within the projection byte limit"
            )
        _content_id(
            self.expected_projection_id,
            field="expected_projection_id",
        )
        _content_id(
            self.expected_projection_result_id,
            field="expected_projection_result_id",
        )
        if not self.expected_projection_id.startswith(
            "search-reference-authority-projection:sha256:"
        ):
            raise CourseReferenceAuthorityError(
                "expected_projection_id has an invalid identity kind"
            )
        if not self.expected_projection_result_id.startswith(
            "search-reference-authority-result:sha256:"
        ):
            raise CourseReferenceAuthorityError(
                "expected_projection_result_id has an invalid identity kind"
            )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "search-reference-authority-projection-read-request",
                {
                    "expected_byte_size": self.expected_byte_size,
                    "expected_projection_id": self.expected_projection_id,
                    "expected_projection_result_id": (
                        self.expected_projection_result_id
                    ),
                    "expected_sha256": self.expected_sha256,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjectionBytesReadResult(DataObjectActionResult):
    """Carry bounded bytes from an injected read-only source."""

    request_id: str
    content: bytes
    content_sha256: str = field(init=False)
    content_byte_size: int = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object."""
        _content_id(self.request_id, field="request_id")
        if type(self.content) is not bytes:
            raise TypeError("content must be exact bytes")
        if not self.content or (
            len(self.content) > _MAX_SEARCH_AUTHORITY_PROJECTION_BYTES
        ):
            raise CourseReferenceAuthorityError(
                "projection bytes exceed the bounded source limit"
            )
        content_sha256 = hashlib.sha256(self.content).hexdigest()
        content_byte_size = len(self.content)
        object.__setattr__(self, "content_sha256", content_sha256)
        object.__setattr__(self, "content_byte_size", content_byte_size)
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "search-reference-authority-projection-bytes-read-result",
                {
                    "content_byte_size": content_byte_size,
                    "content_sha256": content_sha256,
                    "request_id": self.request_id,
                },
            ),
        )


@runtime_checkable
class SearchReferenceAuthorityProjectionBytesSource(Protocol):
    """Supply bounded bytes without exposing runtime location semantics."""

    def action(
        self,
        *,
        request: SearchReferenceAuthorityProjectionReadRequest,
    ) -> SearchReferenceAuthorityProjectionBytesReadResult:
        """Read bytes correlated to one exact semantic request."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchReferenceAuthorityProjectionReadResult(DataObjectActionResult):
    """Return an identity-validated exact owner projection."""

    request_id: str
    source_result_id: str
    projection: SearchReferenceAuthorityProjection
    content_sha256: str
    content_byte_size: int
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate and finalize the immutable data object."""
        _content_id(self.request_id, field="request_id")
        _content_id(self.source_result_id, field="source_result_id")
        if type(self.projection) is not SearchReferenceAuthorityProjection:
            raise TypeError(
                "projection must be SearchReferenceAuthorityProjection"
            )
        _sha256(self.content_sha256, field="content_sha256")
        if (
            type(self.content_byte_size) is not int
            or self.content_byte_size <= 0
            or self.content_byte_size > _MAX_SEARCH_AUTHORITY_PROJECTION_BYTES
        ):
            raise CourseReferenceAuthorityError(
                "content_byte_size must be within the projection byte limit"
            )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "search-reference-authority-projection-read-result",
                {
                    "content_byte_size": self.content_byte_size,
                    "content_sha256": self.content_sha256,
                    "projection_id": self.projection.projection_id,
                    "projection_result_id": self.projection.result_id,
                    "request_id": self.request_id,
                    "source_result_id": self.source_result_id,
                },
            ),
        )


class SearchReferenceAuthorityProjectionReadActionizer(
    DataObjectActionizer[
        SearchReferenceAuthorityProjectionReadRequest,
        SearchReferenceAuthorityProjectionReadResult,
    ]
):
    """Load one canonical projection through an injected bytes source."""

    __slots__ = ("_source",)

    def __init__(
        self,
        *,
        source: SearchReferenceAuthorityProjectionBytesSource,
    ) -> None:
        """Bind the read-only bytes capability."""
        if not isinstance(
            source, SearchReferenceAuthorityProjectionBytesSource
        ):
            raise TypeError("source must implement the bytes source port")
        self._source = source

    def action(
        self,
        *,
        request: SearchReferenceAuthorityProjectionReadRequest,
    ) -> SearchReferenceAuthorityProjectionReadResult:
        """Verify exact bytes before strict owner decoding."""
        if type(request) is not SearchReferenceAuthorityProjectionReadRequest:
            raise TypeError("request has an invalid type")
        source_result = self._source.action(request=request)
        if type(source_result) is not (
            SearchReferenceAuthorityProjectionBytesReadResult
        ):
            raise TypeError("source returned an invalid result type")
        if source_result.request_id != request.request_id:
            raise CourseReferenceAuthorityError(
                "bytes source result is not correlated to the request"
            )
        if source_result.content_byte_size != request.expected_byte_size:
            raise CourseReferenceAuthorityError(
                "projection byte length differs from the request"
            )
        if source_result.content_sha256 != request.expected_sha256:
            raise CourseReferenceAuthorityError(
                "projection SHA-256 differs from the request"
            )
        projection = _decode_search_reference_authority_projection(
            source_result.content
        )
        if projection.projection_id != request.expected_projection_id:
            raise CourseReferenceAuthorityError(
                "projection identity differs from the request"
            )
        if projection.result_id != request.expected_projection_result_id:
            raise CourseReferenceAuthorityError(
                "projection result identity differs from the request"
            )
        return SearchReferenceAuthorityProjectionReadResult(
            request_id=request.request_id,
            source_result_id=source_result.result_id,
            projection=projection,
            content_sha256=source_result.content_sha256,
            content_byte_size=source_result.content_byte_size,
        )


_MAX_SEARCH_AUTHORITY_PROJECTION_BYTES = 10_000_000
_MAX_SEARCH_AUTHORITY_BINDINGS = 10_000
_MAX_SEARCH_AUTHORITY_LINKS = 10_000
_MAX_SEARCH_AUTHORITY_EVIDENCE_IDS = 100_000
_CONTENT_ID = re.compile(r"[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _sha256(value: str, *, field: str) -> str:
    """Validate one lowercase SHA-256 digest."""
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CourseReferenceAuthorityError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _canonical_search_reference_authority_projection_bytes(
    projection: SearchReferenceAuthorityProjection,
) -> bytes:
    """Encode one projection in its sole canonical persisted form."""
    return (
        json.dumps(
            asdict(projection),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _decode_search_reference_authority_projection(
    content: bytes,
) -> SearchReferenceAuthorityProjection:
    """Strictly reconstruct one exact projection from canonical bytes."""
    if type(content) is not bytes:
        raise TypeError("projection content must be exact bytes")
    if not content or len(content) > _MAX_SEARCH_AUTHORITY_PROJECTION_BYTES:
        raise CourseReferenceAuthorityError(
            "projection content exceeds its byte limit"
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CourseReferenceAuthorityError(
            "projection content is not UTF-8"
        ) from error
    try:
        raw = cast(
            object,
            json.loads(text, object_pairs_hook=_unique_json_object),
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise CourseReferenceAuthorityError(
            "projection content is not valid JSON"
        ) from error
    data = _exact_json_object(
        raw,
        fields={
            "bindings",
            "projection_id",
            "result_id",
            "review_projection_id",
        },
        label="Search authority projection",
    )
    bindings_raw = _json_array(
        data["bindings"],
        field="bindings",
        maximum=_MAX_SEARCH_AUTHORITY_BINDINGS,
    )
    projection = SearchReferenceAuthorityProjection(
        review_projection_id=_json_string(
            data["review_projection_id"],
            field="review_projection_id",
        ),
        bindings=tuple(_decode_search_binding(item) for item in bindings_raw),
    )
    supplied_projection_id = _json_string(
        data["projection_id"], field="projection_id"
    )
    supplied_result_id = _json_string(data["result_id"], field="result_id")
    if projection.projection_id != supplied_projection_id:
        raise CourseReferenceAuthorityError(
            "supplied projection_id differs from reconstructed identity"
        )
    if projection.result_id != supplied_result_id:
        raise CourseReferenceAuthorityError(
            "supplied result_id differs from reconstructed identity"
        )
    if (
        _canonical_search_reference_authority_projection_bytes(projection)
        != content
    ):
        raise CourseReferenceAuthorityError(
            "Search authority projection JSON is not canonical"
        )
    return projection


def _decode_search_binding(raw: object) -> SearchReferenceAuthorityBinding:
    """Strictly reconstruct one nested Search authority binding."""
    data = _exact_json_object(
        raw,
        fields={
            "accepted_citekey",
            "authority_binding_id",
            "authority_evidence_ids",
            "bibliographic_work_id",
            "binding_id",
            "candidate_id",
            "canonical_asset_decision_id",
            "identity_decision_id",
            "ingestion_artifact_links",
            "reference_identity_status",
            "source_asset_id",
            "state_projection_id",
        },
        label="Search authority binding",
    )
    links_raw = _json_array(
        data["ingestion_artifact_links"],
        field="ingestion_artifact_links",
        maximum=_MAX_SEARCH_AUTHORITY_LINKS,
    )
    evidence_raw = _json_array(
        data["authority_evidence_ids"],
        field="authority_evidence_ids",
        maximum=_MAX_SEARCH_AUTHORITY_EVIDENCE_IDS,
    )
    binding = SearchReferenceAuthorityBinding(
        candidate_id=_json_string(data["candidate_id"], field="candidate_id"),
        bibliographic_work_id=_json_string(
            data["bibliographic_work_id"],
            field="bibliographic_work_id",
        ),
        reference_identity_status=_json_string(
            data["reference_identity_status"],
            field="reference_identity_status",
        ),
        accepted_citekey=_json_string(
            data["accepted_citekey"], field="accepted_citekey"
        ),
        source_asset_id=_json_string(
            data["source_asset_id"], field="source_asset_id"
        ),
        authority_binding_id=_json_string(
            data["authority_binding_id"], field="authority_binding_id"
        ),
        identity_decision_id=_json_string(
            data["identity_decision_id"], field="identity_decision_id"
        ),
        canonical_asset_decision_id=_json_string(
            data["canonical_asset_decision_id"],
            field="canonical_asset_decision_id",
        ),
        ingestion_artifact_links=tuple(
            _decode_ingestion_link(item) for item in links_raw
        ),
        authority_evidence_ids=tuple(
            _json_string(item, field="authority_evidence_id")
            for item in evidence_raw
        ),
        state_projection_id=_json_string(
            data["state_projection_id"], field="state_projection_id"
        ),
    )
    if binding.binding_id != _json_string(
        data["binding_id"], field="binding_id"
    ):
        raise CourseReferenceAuthorityError(
            "supplied binding_id differs from reconstructed identity"
        )
    return binding


def _decode_ingestion_link(raw: object) -> IngestionArtifactAuthorityLink:
    """Strictly reconstruct one nested Ingestion authority link."""
    data = _exact_json_object(
        raw,
        fields={
            "artifact_verification_result_id",
            "asset_observation_id",
            "document_id",
            "link_id",
            "source_id",
        },
        label="Ingestion artifact authority link",
    )
    link = IngestionArtifactAuthorityLink(
        asset_observation_id=_json_string(
            data["asset_observation_id"], field="asset_observation_id"
        ),
        source_id=_json_string(data["source_id"], field="source_id"),
        document_id=_json_string(data["document_id"], field="document_id"),
        artifact_verification_result_id=_json_string(
            data["artifact_verification_result_id"],
            field="artifact_verification_result_id",
        ),
    )
    if link.link_id != _json_string(data["link_id"], field="link_id"):
        raise CourseReferenceAuthorityError(
            "supplied link_id differs from reconstructed identity"
        )
    return link


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject duplicate object members during JSON construction."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CourseReferenceAuthorityError(
                f"projection JSON contains duplicate field: {key}"
            )
        result[key] = value
    return result


def _exact_json_object(
    value: object,
    *,
    fields: set[str],
    label: str,
) -> dict[str, object]:
    """Require one object with a closed exact field set."""
    if type(value) is not dict:
        raise CourseReferenceAuthorityError(f"{label} must be an object")
    data = cast(dict[str, object], value)
    if set(data) != fields:
        raise CourseReferenceAuthorityError(f"{label} fields are invalid")
    return data


def _json_array(
    value: object,
    *,
    field: str,
    maximum: int,
) -> list[object]:
    """Require one bounded exact JSON array."""
    if type(value) is not list:
        raise CourseReferenceAuthorityError(f"{field} must be an array")
    values = cast(list[object], value)
    if len(values) > maximum:
        raise CourseReferenceAuthorityError(f"{field} exceeds its count limit")
    return values


def _json_string(value: object, *, field: str) -> str:
    """Require one bounded exact JSON string."""
    if type(value) is not str:
        raise CourseReferenceAuthorityError(f"{field} must be a string")
    text = value
    if not text or len(text.encode("utf-8")) > 1_024:
        raise CourseReferenceAuthorityError(f"{field} is outside its limit")
    return text


def _asset_evidence_ids(
    asset: ReferenceAssetAuthorityEvidence,
) -> tuple[str, ...]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    asset
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    values = {
        asset.asset_observation_id,
        *asset.document_binding_ids,
        *asset.ingestion_evidence_ids,
        *(link.link_id for link in asset.ingestion_artifact_links),
    }
    if asset.runtime_evidence_id is not None:
        values.add(asset.runtime_evidence_id)
    return tuple(sorted(values))


def _active_authorities(
    state_projections: tuple[ReferenceStateProjection, ...],
    review_projection: ReviewProjection,
) -> tuple[ActiveReferenceAuthority, ...]:
    """Evaluate one internal trust-boundary operation.

    Parameters
    ----------
    state_projections
        Typed input governed by the function annotation.
    review_projection
        Typed input governed by the function annotation.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    current = {
        item.decision_id: item
        for item in review_projection.human_decision_history
        if item.decision_id in set(review_projection.current_human_decision_ids)
    }
    authorities = []
    for projection in state_projections:
        values = {
            name: _single_projection_value(projection, name)
            for name in (
                "identity_status",
                "proposed_citekey",
                "bibliographic_work_id",
                "active_citekey",
                "alias_citekeys",
                "identity_decision_id",
                "source_asset_id",
                "canonical_asset_decision_id",
                "authority_binding_id",
            )
        }
        if values["identity_status"] != "accepted":
            continue
        identity_decision_id = cast(str | None, values["identity_decision_id"])
        identity_decision = (
            None
            if identity_decision_id is None
            else current.get(identity_decision_id)
        )
        if (
            identity_decision is None
            or identity_decision.dimension
            is not HumanReviewDimension.REFERENCE_IDENTITY
            or identity_decision.decision
            not in {
                ReferenceIdentityDecision.ACCEPT_NEW.value,
                ReferenceIdentityDecision.ACCEPT_EXISTING.value,
                ReferenceIdentityDecision.MERGE.value,
            }
        ):
            continue
        projection_inputs = set(projection.authoritative_input_ids)
        if not {
            projection.subject_id,
            identity_decision.decision_id,
        }.issubset(projection_inputs):
            continue
        if (
            not isinstance(values["proposed_citekey"], str)
            or not isinstance(values["active_citekey"], str)
            or not isinstance(values["bibliographic_work_id"], str)
            or not isinstance(values["alias_citekeys"], list)
            or any(
                not isinstance(item, str)
                for item in cast(list[object], values["alias_citekeys"])
            )
        ):
            continue
        proposed_citekey = values["proposed_citekey"]
        active_citekey = values["active_citekey"]
        work_id = values["bibliographic_work_id"]
        aliases = tuple(values["alias_citekeys"])
        if (
            identity_decision.decision
            == ReferenceIdentityDecision.ACCEPT_NEW.value
        ):
            expected_work_id = _stable_id(
                "bibliographic-work",
                {
                    "candidate_id": projection.subject_id,
                    "creating_decision_id": identity_decision.decision_id,
                },
            )
            if (
                work_id != expected_work_id
                or active_citekey != proposed_citekey
                or aliases
            ):
                continue
        elif identity_decision.decision == (
            ReferenceIdentityDecision.ACCEPT_EXISTING.value
        ):
            if (
                work_id not in identity_decision.evidence_ids
                or active_citekey != proposed_citekey
            ):
                continue
        elif work_id not in identity_decision.evidence_ids or (
            proposed_citekey != active_citekey
            and proposed_citekey not in aliases
        ):
            continue
        asset_decision_id = cast(
            str | None, values["canonical_asset_decision_id"]
        )
        if asset_decision_id is None:
            if not set(identity_decision.evidence_ids).issubset(
                projection_inputs
            ):
                continue
        else:
            asset_decision = current.get(asset_decision_id)
            if (
                asset_decision is None
                or asset_decision.dimension
                is not HumanReviewDimension.CANONICAL_ASSET
                or asset_decision.decision
                != CanonicalAssetDecision.AUTHORIZE.value
                or not {
                    asset_decision.decision_id,
                    *asset_decision.evidence_ids,
                }.issubset(projection_inputs)
            ):
                continue
            work_id = values["bibliographic_work_id"]
            source_asset_id = cast(str | None, values["source_asset_id"])
            binding_id = cast(str | None, values["authority_binding_id"])
            matching_observations = tuple(
                evidence_id
                for evidence_id in asset_decision.evidence_ids
                if source_asset_id
                == _stable_id(
                    "source-asset",
                    {
                        "asset_observation_id": evidence_id,
                        "authorization_decision_id": (
                            asset_decision.decision_id
                        ),
                        "bibliographic_work_id": work_id,
                    },
                )
            )
            if len(matching_observations) != 1:
                continue
            expected_binding_id = _stable_id(
                "reference-source-asset-binding",
                {
                    "asset_observation_id": matching_observations[0],
                    "bibliographic_work_id": work_id,
                    "candidate_id": projection.subject_id,
                    "canonical_asset_decision_id": (asset_decision.decision_id),
                    "identity_decision_id": identity_decision.decision_id,
                    "source_asset_id": source_asset_id,
                },
            )
            if binding_id != expected_binding_id:
                continue
        authority = ActiveReferenceAuthority(
            candidate_id=projection.subject_id,
            state_projection_id=projection.projection_id,
            bibliographic_work_id=values["bibliographic_work_id"],
            active_citekey=values["active_citekey"],
            alias_citekeys=tuple(cast(list[str], values["alias_citekeys"])),
            identity_decision_id=cast(str, identity_decision_id),
            source_asset_id=cast(str | None, values["source_asset_id"]),
            canonical_asset_decision_id=asset_decision_id,
            authority_binding_id=cast(
                str | None, values["authority_binding_id"]
            ),
        )
        authorities.append(authority)
    by_candidate: dict[str, ActiveReferenceAuthority] = {}
    for authority in sorted(
        authorities, key=lambda item: item.state_projection_id
    ):
        previous = by_candidate.get(authority.candidate_id)
        if previous is not None:
            previous_complete = previous.source_asset_id is not None
            current_complete = authority.source_asset_id is not None
            if previous_complete == current_complete:
                raise CourseReferenceAuthorityError(
                    "candidate has ambiguous active state projections"
                )
            if previous_complete:
                continue
        by_candidate[authority.candidate_id] = authority
    return tuple(
        sorted(by_candidate.values(), key=lambda item: item.candidate_id)
    )


def _single_projection_value(
    projection: ReferenceStateProjection,
    field_name: str,
) -> object | None:
    """Read one unambiguous JSON value from a state projection."""
    item = projection.field(field_name)
    if len(item.values) != 1 or item.values[0].value_json is None:
        return None
    value: object = json.loads(item.values[0].value_json)
    return value
