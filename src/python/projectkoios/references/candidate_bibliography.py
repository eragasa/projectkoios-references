"""Pure candidate-bibliography union and exact-entry export."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.identity import SourceBibliographyObservation
from projectkoios.references.path_safety import validate_citekey

CANDIDATE_BIBLIOGRAPHY_EXPORT_CONTRACT_ID = (
    "projectkoios.references.candidate-bibliography-export@0.1.0"
)
CANDIDATE_BIBLIOGRAPHY_EXPORT_SCHEMA_VERSION = 1
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_COLLECTIONS = 32
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES = 10_000
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES = 50_000_000
CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR = b"\n\n"

_COLLECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,199}")
_ENTRY_HEADER = re.compile(
    r"\A@[A-Za-z][A-Za-z0-9_-]{0,63}\s*[({]\s*([^,\s]+)\s*,",
    re.ASCII,
)


class CandidateBibliographyExportError(ValueError):
    """Raised when a candidate bibliography cannot be exported exactly."""


class CandidateBibliographyExportStatus(StrEnum):
    """Fixed authority status for private candidate-bibliography output."""

    PROPOSED_NONCANONICAL = "proposed-noncanonical-private-drafting"


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographySourceDeclaration(DataObjectModel):
    """Bind one collection ID to exact source-bibliography observations."""

    collection_id: str
    observations: tuple[SourceBibliographyObservation, ...]
    declaration_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_collection_id(self.collection_id)
        if not isinstance(self.observations, tuple) or any(
            type(item) is not SourceBibliographyObservation
            for item in self.observations
        ):
            raise TypeError(
                "observations must be a SourceBibliographyObservation tuple"
            )
        if not self.observations:
            raise CandidateBibliographyExportError(
                "source declaration observations must be non-empty"
            )
        if len(self.observations) > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES:
            raise CandidateBibliographyExportError(
                "source declaration exceeds the entry limit"
            )
        first = self.observations[0]
        source_identity = _source_identity(first)
        if any(
            _source_identity(observation) != source_identity
            for observation in self.observations
        ):
            raise CandidateBibliographyExportError(
                "source declaration observations have mixed provenance"
            )
        if (
            first.bibliography_byte_size
            > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES
        ):
            raise CandidateBibliographyExportError(
                "source bibliography exceeds the byte limit"
            )
        indexes = tuple(item.entry_index for item in self.observations)
        if indexes != tuple(range(len(self.observations))):
            raise CandidateBibliographyExportError(
                "source observations must use contiguous source order"
            )
        citekeys = tuple(item.observed_citekey for item in self.observations)
        if len(set(citekeys)) != len(citekeys):
            raise CandidateBibliographyExportError(
                "source declaration contains duplicate citekeys"
            )
        observation_ids = tuple(
            item.observation_id for item in self.observations
        )
        if len(set(observation_ids)) != len(observation_ids):
            raise CandidateBibliographyExportError(
                "source declaration contains duplicate observations"
            )
        for observation in self.observations:
            _validate_entry_header(observation)
        object.__setattr__(
            self,
            "declaration_id",
            _stable_id(
                "candidate-bibliography-source-declaration",
                {
                    "collection_id": self.collection_id,
                    "contract_id": CANDIDATE_BIBLIOGRAPHY_EXPORT_CONTRACT_ID,
                    "observation_ids": observation_ids,
                    "schema_version": (
                        CANDIDATE_BIBLIOGRAPHY_EXPORT_SCHEMA_VERSION
                    ),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyExportRequest(DataObjectActionRequest):
    """Request an order-independent union of explicit candidate sources."""

    sources: tuple[CandidateBibliographySourceDeclaration, ...]
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.sources, tuple) or any(
            type(item) is not CandidateBibliographySourceDeclaration
            for item in self.sources
        ):
            raise TypeError(
                "sources must be a CandidateBibliographySourceDeclaration tuple"
            )
        if not self.sources:
            raise CandidateBibliographyExportError(
                "candidate bibliography sources must be non-empty"
            )
        if len(self.sources) > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_COLLECTIONS:
            raise CandidateBibliographyExportError(
                "candidate bibliography exceeds the collection limit"
            )
        collection_ids = tuple(item.collection_id for item in self.sources)
        if len(set(collection_ids)) != len(collection_ids):
            raise CandidateBibliographyExportError(
                "candidate bibliography contains duplicate collection IDs"
            )
        declaration_ids = tuple(item.declaration_id for item in self.sources)
        if len(set(declaration_ids)) != len(declaration_ids):
            raise CandidateBibliographyExportError(
                "candidate bibliography contains duplicate declarations"
            )
        total_declared_bytes = sum(
            source.observations[0].bibliography_byte_size
            for source in self.sources
        )
        if total_declared_bytes > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES:
            raise CandidateBibliographyExportError(
                "candidate bibliography sources exceed the byte limit"
            )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "candidate-bibliography-export-request",
                {
                    "contract_id": CANDIDATE_BIBLIOGRAPHY_EXPORT_CONTRACT_ID,
                    "source_declaration_ids": sorted(declaration_ids),
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyExportProvenance(DataObjectModel):
    """One exported collection's exact source and observation provenance."""

    collection_id: str
    declaration_id: str
    source_id: str
    asserted_source_revision: str | None
    source_path: str
    bibliography_sha256: str
    bibliography_byte_size: int
    observation_ids: tuple[str, ...]
    observed_citekeys: tuple[str, ...]

    @classmethod
    def from_declaration(
        cls,
        declaration: CandidateBibliographySourceDeclaration,
    ) -> CandidateBibliographyExportProvenance:
        """Project one already-validated declaration into result provenance."""
        first = declaration.observations[0]
        return cls(
            collection_id=declaration.collection_id,
            declaration_id=declaration.declaration_id,
            source_id=first.source_id,
            asserted_source_revision=first.asserted_source_revision,
            source_path=first.source_path,
            bibliography_sha256=first.bibliography_sha256,
            bibliography_byte_size=first.bibliography_byte_size,
            observation_ids=tuple(
                item.observation_id for item in declaration.observations
            ),
            observed_citekeys=tuple(
                item.observed_citekey for item in declaration.observations
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyExportResult(DataObjectActionResult):
    """Return exact candidate entries with bounded provenance and digest."""

    request: CandidateBibliographyExportRequest
    provenance: tuple[CandidateBibliographyExportProvenance, ...]
    citekeys: tuple[str, ...]
    bibliography: bytes
    status: CandidateBibliographyExportStatus = (
        CandidateBibliographyExportStatus.PROPOSED_NONCANONICAL
    )
    bibliography_sha256: str = field(init=False)
    bibliography_byte_size: int = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CandidateBibliographyExportRequest:
            raise TypeError(
                "request must be a CandidateBibliographyExportRequest"
            )
        if self.status is not (
            CandidateBibliographyExportStatus.PROPOSED_NONCANONICAL
        ):
            raise CandidateBibliographyExportError(
                "candidate bibliography status exceeds private drafting"
            )
        expected_provenance, expected_citekeys, expected_bibliography = (
            _project(self.request)
        )
        if self.provenance != expected_provenance:
            raise CandidateBibliographyExportError(
                "export provenance does not match its request"
            )
        if self.citekeys != expected_citekeys:
            raise CandidateBibliographyExportError(
                "export citekeys do not match its request"
            )
        if self.bibliography != expected_bibliography:
            raise CandidateBibliographyExportError(
                "export bibliography does not match its request"
            )
        digest = hashlib.sha256(self.bibliography).hexdigest()
        object.__setattr__(self, "bibliography_sha256", digest)
        object.__setattr__(
            self,
            "bibliography_byte_size",
            len(self.bibliography),
        )
        object.__setattr__(
            self,
            "result_id",
            _stable_id(
                "candidate-bibliography-export-result",
                {
                    "bibliography_byte_size": len(self.bibliography),
                    "bibliography_sha256": digest,
                    "citekeys": self.citekeys,
                    "contract_id": CANDIDATE_BIBLIOGRAPHY_EXPORT_CONTRACT_ID,
                    "request_id": self.request.request_id,
                    "source_declaration_ids": tuple(
                        item.declaration_id for item in self.provenance
                    ),
                    "status": self.status.value,
                },
            ),
        )


class CandidateBibliographyExporter(
    DataObjectActionizer[
        CandidateBibliographyExportRequest,
        CandidateBibliographyExportResult,
    ]
):
    """Purely union exact observed entries without accepting their identity."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CandidateBibliographyExportRequest,
    ) -> CandidateBibliographyExportResult:
        return self.export(request=request)

    def export(
        self,
        *,
        request: CandidateBibliographyExportRequest,
    ) -> CandidateBibliographyExportResult:
        """Return the deterministic exact-entry union for one request."""
        if type(request) is not CandidateBibliographyExportRequest:
            raise TypeError(
                "request must be a CandidateBibliographyExportRequest"
            )
        provenance, citekeys, bibliography = _project(request)
        return CandidateBibliographyExportResult(
            request=request,
            provenance=provenance,
            citekeys=citekeys,
            bibliography=bibliography,
        )


def _project(
    request: CandidateBibliographyExportRequest,
) -> tuple[
    tuple[CandidateBibliographyExportProvenance, ...],
    tuple[str, ...],
    bytes,
]:
    provenance = tuple(
        CandidateBibliographyExportProvenance.from_declaration(source)
        for source in sorted(
            request.sources,
            key=lambda item: (item.collection_id, item.declaration_id),
        )
    )
    entries: dict[str, bytes] = {}
    count = 0
    for source in request.sources:
        for observation in source.observations:
            count += 1
            if count > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES:
                raise CandidateBibliographyExportError(
                    "candidate bibliography exceeds the entry limit"
                )
            try:
                entry = observation.verbatim_entry.encode("utf-8")
            except UnicodeEncodeError as error:
                raise CandidateBibliographyExportError(
                    "candidate bibliography entry is not UTF-8 encodable"
                ) from error
            existing = entries.get(observation.observed_citekey)
            if existing is not None and existing != entry:
                raise CandidateBibliographyExportError(
                    "candidate bibliography citekey collision: "
                    f"{observation.observed_citekey}"
                )
            entries[observation.observed_citekey] = entry
    citekeys = tuple(sorted(entries))
    parts = tuple(entries[citekey] for citekey in citekeys)
    output_size = sum(len(part) for part in parts)
    if parts:
        output_size += len(CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR) * (
            len(parts) - 1
        )
        output_size += 1
    if output_size > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES:
        raise CandidateBibliographyExportError(
            "candidate bibliography export exceeds the byte limit"
        )
    bibliography = CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR.join(parts) + b"\n"
    return provenance, citekeys, bibliography


def _source_identity(
    observation: SourceBibliographyObservation,
) -> tuple[str, str | None, str, str, int]:
    return (
        observation.source_id,
        observation.asserted_source_revision,
        observation.source_path,
        observation.bibliography_sha256,
        observation.bibliography_byte_size,
    )


def _validate_collection_id(collection_id: str) -> None:
    if (
        type(collection_id) is not str
        or _COLLECTION_ID.fullmatch(collection_id) is None
    ):
        raise CandidateBibliographyExportError(
            "collection_id must be a bounded ASCII identifier"
        )


def _validate_entry_header(
    observation: SourceBibliographyObservation,
) -> None:
    match = _ENTRY_HEADER.match(observation.verbatim_entry)
    if match is None:
        raise CandidateBibliographyExportError(
            "source observation has a malformed BibTeX entry header"
        )
    declared_citekey = match.group(1)
    validate_citekey(declared_citekey, field="declared citekey")
    if declared_citekey != observation.observed_citekey:
        raise CandidateBibliographyExportError(
            "source observation citekey differs from its BibTeX entry"
        )


def _stable_id(kind: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(encoded).hexdigest()}"
