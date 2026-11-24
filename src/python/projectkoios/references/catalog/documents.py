"""Small, identity-stable document reads over a References catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol, Self, cast

import projectkoios.base as base
import projectkoios.references.identity as identity
import projectkoios.references.models as models
import projectkoios.references.review as review

_MAX_DOCUMENTS = 1_000
_MAX_TEXT = 16_384


class ReferenceDocumentReadError(ValueError):
    """Raised when document bindings and catalog evidence disagree."""


class ReferenceDocumentNotFound(ReferenceDocumentReadError):
    """Raised when one requested visible document is absent."""


class ReferenceDocumentAudience(StrEnum):
    """Visibility boundary for document reads."""

    CONTROL = "control"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentBinding(base.DataObjectModel):
    """Bind one stable document ID to one observed reference candidate."""

    document_id: str
    proposed_citekey: str
    collection_id: str
    collection_label: str
    filename: str

    def __post_init__(self) -> None:
        for name, value in (
            ("document_id", self.document_id),
            ("proposed_citekey", self.proposed_citekey),
            ("collection_id", self.collection_id),
            ("collection_label", self.collection_label),
            ("filename", self.filename),
        ):
            if not value or len(value) > _MAX_TEXT or value != value.strip():
                raise ReferenceDocumentReadError(
                    f"reference document {name} is invalid"
                )
        if self.filename != Path(self.filename).name:
            raise ReferenceDocumentReadError(
                "reference document filename must be a basename"
            )

    def to_dict(self) -> dict[str, str]:
        """Return the exact domain-owned binding mapping."""
        return {
            "collection_id": self.collection_id,
            "collection_label": self.collection_label,
            "document_id": self.document_id,
            "filename": self.filename,
            "proposed_citekey": self.proposed_citekey,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Reconstruct one binding from its exact mapping."""
        fields = {
            "collection_id",
            "collection_label",
            "document_id",
            "filename",
            "proposed_citekey",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ReferenceDocumentReadError(
                "reference document binding fields differ"
            )
        document = cast(dict[str, object], value)
        if any(not isinstance(document[name], str) for name in fields):
            raise ReferenceDocumentReadError(
                "reference document binding values are malformed"
            )
        return cls(
            document_id=cast(str, document["document_id"]),
            proposed_citekey=cast(str, document["proposed_citekey"]),
            collection_id=cast(str, document["collection_id"]),
            collection_label=cast(str, document["collection_label"]),
            filename=cast(str, document["filename"]),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentRegistry(base.DataObjectModel):
    """Explicit stable identities for one bounded catalog slice."""

    bindings: tuple[ReferenceDocumentBinding, ...]
    registry_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.bindings or len(self.bindings) > _MAX_DOCUMENTS:
            raise ReferenceDocumentReadError(
                "reference document registry is outside its bounds"
            )
        if any(
            not isinstance(binding, ReferenceDocumentBinding)
            for binding in self.bindings
        ):
            raise TypeError(
                "reference document registry requires typed bindings"
            )
        if tuple(binding.document_id for binding in self.bindings) != tuple(
            sorted(binding.document_id for binding in self.bindings)
        ):
            raise ReferenceDocumentReadError(
                "reference document bindings must be in document order"
            )
        for values, label in (
            (
                tuple(binding.document_id for binding in self.bindings),
                "document IDs",
            ),
            (
                tuple(binding.proposed_citekey for binding in self.bindings),
                "citekeys",
            ),
            (
                tuple(binding.filename for binding in self.bindings),
                "filenames",
            ),
        ):
            if len(values) != len(set(values)):
                raise ReferenceDocumentReadError(
                    f"reference document registry has duplicate {label}"
                )
        payload = [binding.to_dict() for binding in self.bindings]
        object.__setattr__(
            self,
            "registry_id",
            self.identity_for(payload=payload),
        )

    @staticmethod
    def identity_for(*, payload: object) -> str:
        """Return the content identity for canonical registry data."""
        content = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return (
            "reference-document-registry:sha256:"
            + hashlib.sha256(content).hexdigest()
        )

    def to_dict(self) -> dict[str, object]:
        """Return the exact versioned registry mapping."""
        return {
            "schema_version": 1,
            "documents": [binding.to_dict() for binding in self.bindings],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Reconstruct one registry from its exact versioned mapping."""
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "documents",
        }:
            raise ReferenceDocumentReadError(
                "reference document registry fields differ"
            )
        if value["schema_version"] != 1:
            raise ReferenceDocumentReadError(
                "reference document registry schema is unsupported"
            )
        raw_documents = value["documents"]
        if not isinstance(raw_documents, list):
            raise ReferenceDocumentReadError(
                "reference document registry entries are malformed"
            )
        return cls(
            bindings=tuple(
                ReferenceDocumentBinding.from_dict(raw_document)
                for raw_document in raw_documents
            )
        )

    def to_json(self) -> str:
        """Serialize canonical JSON through :meth:`to_dict`."""
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def from_json(cls, content: str) -> Self:
        """Parse JSON and reconstruct through :meth:`from_dict`."""
        try:
            value = json.loads(
                content,
                object_pairs_hook=cls._without_duplicate_members,
            )
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ReferenceDocumentReadError(
                "reference document registry is malformed JSON"
            ) from error
        return cls.from_dict(value)

    @staticmethod
    def _without_duplicate_members(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in pairs:
            if name in result:
                raise ReferenceDocumentReadError(
                    f"duplicate reference document registry member: {name}"
                )
            result[name] = value
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocument(base.DataObjectModel):
    """Privacy-reduced document metadata for application composition."""

    document_id: str
    proposed_citekey: str
    collection_id: str
    collection_label: str
    filename: str
    entry_type: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None
    source_asset_count: int
    source_status: str
    review_status: str
    identity_status: str
    citekey_status: str
    publication_eligibility: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentReadRequest(base.DataObjectActionRequest):
    """Request bounded document metadata for one explicit audience."""

    registry_id: str
    audience: ReferenceDocumentAudience
    document_id: str | None = None
    max_documents: int = 100
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.registry_id.startswith(
            "reference-document-registry:sha256:"
        ):
            raise ReferenceDocumentReadError(
                "reference document registry identity is invalid"
            )
        if not isinstance(self.audience, ReferenceDocumentAudience):
            raise TypeError("audience must be a ReferenceDocumentAudience")
        if self.document_id is not None and not self.document_id:
            raise ReferenceDocumentReadError("document ID is empty")
        if not 1 <= self.max_documents <= _MAX_DOCUMENTS:
            raise ReferenceDocumentReadError(
                "reference document limit is outside its bounds"
            )
        payload = {
            "audience": self.audience.value,
            "document_id": self.document_id,
            "max_documents": self.max_documents,
            "registry_id": self.registry_id,
        }
        object.__setattr__(
            self,
            "request_id",
            "reference-document-read-request:sha256:"
            + hashlib.sha256(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceDocumentReadResult(base.DataObjectActionResult):
    """Bind one read request to its ordered visible documents."""

    request: ReferenceDocumentReadRequest
    documents: tuple[ReferenceDocument, ...]
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ReferenceDocumentReadRequest):
            raise TypeError("request must be a ReferenceDocumentReadRequest")
        if any(
            not isinstance(document, ReferenceDocument)
            for document in self.documents
        ):
            raise TypeError("documents must contain ReferenceDocument values")
        if len(self.documents) > self.request.max_documents:
            raise ReferenceDocumentReadError(
                "reference document result exceeds its request"
            )
        if tuple(document.document_id for document in self.documents) != tuple(
            sorted(document.document_id for document in self.documents)
        ):
            raise ReferenceDocumentReadError(
                "reference document result is unordered"
            )
        payload = {
            "documents": [asdict(document) for document in self.documents],
            "request_id": self.request.request_id,
        }
        object.__setattr__(
            self,
            "result_id",
            "reference-document-read-result:sha256:"
            + hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )


class ReferenceDocumentCatalog(Protocol):
    """Catalog evidence required by the document reader."""

    def read_candidates(self) -> tuple[identity.ReferenceCandidate, ...]: ...

    def read_observations(
        self,
    ) -> tuple[identity.SourceBibliographyObservation, ...]: ...

    def read_source_assets(
        self,
        *,
        max_records: int | None = None,
    ) -> tuple[models.SourceAssetRecord, ...]: ...

    def read_review_projection(self) -> review.ReviewProjection: ...


class ReferenceDocumentReader(
    base.DataObjectActionizer[
        ReferenceDocumentReadRequest,
        ReferenceDocumentReadResult,
    ]
):
    """Read documents from explicit bindings and catalog evidence."""

    __slots__ = ("catalog", "registry")

    def __init__(
        self,
        *,
        catalog: ReferenceDocumentCatalog,
        registry: ReferenceDocumentRegistry,
    ) -> None:
        self.catalog = catalog
        self.registry = registry

    def action(
        self,
        *,
        request: ReferenceDocumentReadRequest,
    ) -> ReferenceDocumentReadResult:
        """Return the visible documents for one exact request."""
        if not isinstance(request, ReferenceDocumentReadRequest):
            raise TypeError("request must be a ReferenceDocumentReadRequest")
        if request.registry_id != self.registry.registry_id:
            raise ReferenceDocumentReadError(
                "reference document request uses another registry"
            )
        if request.audience is ReferenceDocumentAudience.PUBLIC:
            if request.document_id is not None:
                raise ReferenceDocumentNotFound(
                    f"reference document {request.document_id!r} was not found"
                )
            return ReferenceDocumentReadResult(request=request, documents=())

        documents = self._control_documents()
        if len(documents) > request.max_documents:
            raise ReferenceDocumentReadError(
                "reference documents exceed the requested limit"
            )
        if request.document_id is None:
            selected = documents
        else:
            selected = tuple(
                document
                for document in documents
                if document.document_id == request.document_id
            )
            if not selected:
                raise ReferenceDocumentNotFound(
                    f"reference document {request.document_id!r} was not found"
                )
        return ReferenceDocumentReadResult(
            request=request,
            documents=selected,
        )

    def _control_documents(self) -> tuple[ReferenceDocument, ...]:
        registry_citekeys = {
            binding.proposed_citekey for binding in self.registry.bindings
        }
        candidates = tuple(
            candidate
            for candidate in self.catalog.read_candidates()
            if candidate.proposed_citekey in registry_citekeys
        )
        candidate_by_citekey = {
            candidate.proposed_citekey: candidate for candidate in candidates
        }
        if (
            len(candidate_by_citekey) != len(candidates)
            or set(candidate_by_citekey) != registry_citekeys
        ):
            raise ReferenceDocumentReadError(
                "reference document registry differs from catalog candidates"
            )
        selected_candidate_ids = {
            candidate.candidate_id for candidate in candidates
        }
        assets_by_candidate: dict[str, list[models.SourceAssetRecord]] = {}
        for asset in self.catalog.read_source_assets():
            if asset.candidate_id in selected_candidate_ids:
                assets_by_candidate.setdefault(asset.candidate_id, []).append(
                    asset
                )
        asset_backed_citekeys = {
            candidate.proposed_citekey
            for candidate in candidates
            if candidate.candidate_id in assets_by_candidate
        }
        if asset_backed_citekeys != registry_citekeys:
            raise ReferenceDocumentReadError(
                "reference document registry differs from asset-backed catalog"
            )

        observations = {
            observation.observation_id: observation
            for observation in self.catalog.read_observations()
        }
        projection = self.catalog.read_review_projection()
        reviewed_subjects = self._reviewed_subjects(projection)
        result: list[ReferenceDocument] = []
        for binding in self.registry.bindings:
            candidate = candidate_by_citekey[binding.proposed_citekey]
            self._validate_collection(binding, candidate, observations)
            candidate_assets = tuple(
                assets_by_candidate[candidate.candidate_id]
            )
            statuses = {asset.asset_status for asset in candidate_assets}
            source_status = (
                next(iter(statuses))
                if len(statuses) == 1
                else "multiple-source-observations"
            )
            result.append(
                ReferenceDocument(
                    document_id=binding.document_id,
                    proposed_citekey=candidate.proposed_citekey,
                    collection_id=binding.collection_id,
                    collection_label=binding.collection_label,
                    filename=binding.filename,
                    entry_type=candidate.entry_type,
                    title=candidate.title,
                    authors=candidate.authors,
                    year=candidate.year,
                    source_asset_count=len(candidate_assets),
                    source_status=source_status,
                    review_status=(
                        "recorded"
                        if candidate.candidate_id in reviewed_subjects
                        else "not-established"
                    ),
                    identity_status=candidate.lifecycle_status,
                    citekey_status=candidate.citekey_status,
                    publication_eligibility="not-established",
                )
            )
        return tuple(result)

    @staticmethod
    def _reviewed_subjects(
        projection: review.ReviewProjection,
    ) -> set[str]:
        current_technical = set(projection.current_technical_record_ids)
        current_human = set(projection.current_human_decision_ids)
        return {
            item.subject_id
            for item in projection.technical_history
            if item.record_id in current_technical
        } | {
            item.subject_id
            for item in projection.human_decision_history
            if item.decision_id in current_human
        }

    @staticmethod
    def _validate_collection(
        binding: ReferenceDocumentBinding,
        candidate: identity.ReferenceCandidate,
        observations: dict[str, identity.SourceBibliographyObservation],
    ) -> None:
        try:
            sources = {
                (
                    observations[observation_id].source_id,
                    observations[observation_id].source_path,
                )
                for observation_id in candidate.source_observation_ids
            }
        except KeyError as error:
            raise ReferenceDocumentReadError(
                "reference candidate observation is missing"
            ) from error
        expected = (
            f"catalog-collection:{binding.collection_id}",
            f"{binding.collection_id}.bib",
        )
        if sources != {expected}:
            raise ReferenceDocumentReadError(
                "reference document collection binding differs"
            )
        if PurePosixPath(expected[1]).stem != binding.collection_id:
            raise ReferenceDocumentReadError(
                "reference document collection identity differs"
            )
