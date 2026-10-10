"""Pure candidate-bibliography union and exact-entry export."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.biblatex import biblatex_parser_identity
from projectkoios.references.identity import SourceBibliographyObservation
from projectkoios.references.path_safety import validate_citekey
from pybtex.database import parse_string  # type: ignore[import-untyped]
from pybtex.scanner import PybtexSyntaxError  # type: ignore[import-untyped]

CANDIDATE_BIBLIOGRAPHY_EXPORT_CONTRACT_ID = (
    "projectkoios.references.candidate-bibliography-export@0.1.0"
)
CANDIDATE_BIBLIOGRAPHY_EXPORT_SCHEMA_VERSION = 1
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_COLLECTIONS = 32
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES = 10_000
CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES = 50_000_000
CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR = b"\n\n"
CANDIDATE_BIBLIOGRAPHY_RENDER_CONTRACT_ID = (
    "projectkoios.references.candidate-bibliography-render@0.1.0"
)
CANDIDATE_BIBLIOGRAPHY_RENDERER_NAME = (
    "projectkoios-references-candidate-bibliography-renderer"
)
CANDIDATE_BIBLIOGRAPHY_RENDERER_VERSION = "0.1.0"

_COLLECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,199}")
_ENTRY_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}", re.ASCII)
_ENTRY_HEADER = re.compile(
    r"\A@[A-Za-z][A-Za-z0-9_-]{0,63}\s*[({]\s*([^,\s]+)\s*,",
    re.ASCII,
)
_RENDERABLE_FIELDS = frozenset(
    {
        "address",
        "annote",
        "author",
        "booktitle",
        "chapter",
        "date",
        "doi",
        "edition",
        "editor",
        "eprint",
        "howpublished",
        "institution",
        "isbn",
        "journal",
        "language",
        "location",
        "month",
        "note",
        "number",
        "organization",
        "pages",
        "publisher",
        "school",
        "series",
        "title",
        "type",
        "urldate",
        "url",
        "version",
        "volume",
        "year",
    }
)
_RENDERABLE_PERSON_ROLES = frozenset({"author", "editor"})
_TEX_ESCAPES = {
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "$": r"\$",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


class _PybtexPerson(Protocol):
    def __str__(self) -> str: ...


class _PybtexEntry(Protocol):
    type: str
    fields: Mapping[str, str]
    persons: Mapping[str, Sequence[_PybtexPerson]]


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


class CandidateBibliographyRenderError(CandidateBibliographyExportError):
    """Raised when normalized fields cannot be rendered safely for TeX."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyRenderRequest(DataObjectActionRequest):
    """Request a render-safe projection of one exact candidate export."""

    source: CandidateBibliographyExportRequest
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.source) is not CandidateBibliographyExportRequest:
            raise TypeError(
                "source must be a CandidateBibliographyExportRequest"
            )
        object.__setattr__(
            self,
            "request_id",
            _stable_id(
                "candidate-bibliography-render-request",
                {
                    "contract_id": CANDIDATE_BIBLIOGRAPHY_RENDER_CONTRACT_ID,
                    "source_request_id": self.source.request_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyRenderedEntry(DataObjectModel):
    """One normalized, escaped entry bound to exact source observations."""

    citekey: str
    entry_type: str
    normalized_fields: tuple[tuple[str, str], ...]
    source_observation_ids: tuple[str, ...]
    rendered_entry: bytes
    entry_id: str = field(init=False)

    def __post_init__(self) -> None:
        validate_citekey(self.citekey, field="rendered citekey")
        if (
            _ENTRY_TYPE.fullmatch(self.entry_type) is None
            or self.entry_type != self.entry_type.lower()
        ):
            raise CandidateBibliographyRenderError(
                "rendered entry type is malformed"
            )
        if not isinstance(self.normalized_fields, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or any(type(value) is not str for value in item)
            for item in self.normalized_fields
        ):
            raise TypeError("normalized_fields must be string pairs")
        if not self.normalized_fields:
            raise CandidateBibliographyRenderError(
                "normalized fields must be non-empty"
            )
        names = tuple(item[0] for item in self.normalized_fields)
        if names != tuple(sorted(set(names))):
            raise CandidateBibliographyRenderError(
                "normalized fields must use unique lexical order"
            )
        if any(name not in _RENDERABLE_FIELDS for name in names):
            raise CandidateBibliographyRenderError(
                "normalized fields contain an unsupported field"
            )
        for name, value in self.normalized_fields:
            if _normalize_render_text(value, field=name) != value:
                raise CandidateBibliographyRenderError(
                    "normalized field value is not canonical"
                )
        if (
            not isinstance(self.source_observation_ids, tuple)
            or not self.source_observation_ids
            or any(
                type(item) is not str or not item
                for item in self.source_observation_ids
            )
            or self.source_observation_ids
            != tuple(sorted(set(self.source_observation_ids)))
        ):
            raise CandidateBibliographyRenderError(
                "source observation IDs must use unique lexical order"
            )
        if (
            not isinstance(self.rendered_entry, bytes)
            or not self.rendered_entry
            or len(self.rendered_entry)
            > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES
        ):
            raise CandidateBibliographyRenderError(
                "rendered entry bytes are empty or oversized"
            )
        if self.rendered_entry != _format_rendered_entry(
            citekey=self.citekey,
            entry_type=self.entry_type,
            normalized_fields=self.normalized_fields,
        ):
            raise CandidateBibliographyRenderError(
                "rendered entry does not match its normalized fields"
            )
        object.__setattr__(
            self,
            "entry_id",
            _stable_id(
                "candidate-bibliography-rendered-entry",
                {
                    "citekey": self.citekey,
                    "entry_type": self.entry_type,
                    "normalized_fields": self.normalized_fields,
                    "rendered_entry_sha256": hashlib.sha256(
                        self.rendered_entry
                    ).hexdigest(),
                    "source_observation_ids": self.source_observation_ids,
                },
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateBibliographyRenderResult(DataObjectActionResult):
    """Return a replayed TeX-safe projection without changing observations."""

    request: CandidateBibliographyRenderRequest
    provenance: tuple[CandidateBibliographyExportProvenance, ...]
    entries: tuple[CandidateBibliographyRenderedEntry, ...]
    bibliography: bytes
    status: CandidateBibliographyExportStatus = (
        CandidateBibliographyExportStatus.PROPOSED_NONCANONICAL
    )
    parser_identity: str = field(init=False)
    source_export_result_id: str = field(init=False)
    source_bibliography_sha256: str = field(init=False)
    source_bibliography_byte_size: int = field(init=False)
    bibliography_sha256: str = field(init=False)
    bibliography_byte_size: int = field(init=False)
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not CandidateBibliographyRenderRequest:
            raise TypeError(
                "request must be a CandidateBibliographyRenderRequest"
            )
        if self.status is not (
            CandidateBibliographyExportStatus.PROPOSED_NONCANONICAL
        ):
            raise CandidateBibliographyRenderError(
                "rendered bibliography status exceeds private drafting"
            )
        source_export, expected_entries, expected_bibliography = (
            _render_project(self.request)
        )
        if self.provenance != source_export.provenance:
            raise CandidateBibliographyRenderError(
                "render provenance does not match its exact source export"
            )
        if self.entries != expected_entries:
            raise CandidateBibliographyRenderError(
                "rendered entries do not match their normalized fields"
            )
        if self.bibliography != expected_bibliography:
            raise CandidateBibliographyRenderError(
                "rendered bibliography does not match its request"
            )
        parser_identity = biblatex_parser_identity()
        digest = hashlib.sha256(self.bibliography).hexdigest()
        object.__setattr__(self, "parser_identity", parser_identity)
        object.__setattr__(
            self,
            "source_export_result_id",
            source_export.result_id,
        )
        object.__setattr__(
            self,
            "source_bibliography_sha256",
            source_export.bibliography_sha256,
        )
        object.__setattr__(
            self,
            "source_bibliography_byte_size",
            source_export.bibliography_byte_size,
        )
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
                "candidate-bibliography-render-result",
                {
                    "bibliography_byte_size": len(self.bibliography),
                    "bibliography_sha256": digest,
                    "contract_id": CANDIDATE_BIBLIOGRAPHY_RENDER_CONTRACT_ID,
                    "entry_ids": tuple(item.entry_id for item in self.entries),
                    "parser_identity": parser_identity,
                    "renderer_name": CANDIDATE_BIBLIOGRAPHY_RENDERER_NAME,
                    "renderer_version": CANDIDATE_BIBLIOGRAPHY_RENDERER_VERSION,
                    "request_id": self.request.request_id,
                    "source_export_result_id": source_export.result_id,
                    "status": self.status.value,
                },
            ),
        )


class CandidateBibliographyRenderer(
    DataObjectActionizer[
        CandidateBibliographyRenderRequest,
        CandidateBibliographyRenderResult,
    ]
):
    """Render parsed candidate fields with bounded TeX escaping."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CandidateBibliographyRenderRequest,
    ) -> CandidateBibliographyRenderResult:
        return self.render(request=request)

    def render(
        self,
        *,
        request: CandidateBibliographyRenderRequest,
    ) -> CandidateBibliographyRenderResult:
        """Return one deterministic render-safe candidate bibliography."""
        if type(request) is not CandidateBibliographyRenderRequest:
            raise TypeError(
                "request must be a CandidateBibliographyRenderRequest"
            )
        source_export, entries, bibliography = _render_project(request)
        return CandidateBibliographyRenderResult(
            request=request,
            provenance=source_export.provenance,
            entries=entries,
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


def _render_project(
    request: CandidateBibliographyRenderRequest,
) -> tuple[
    CandidateBibliographyExportResult,
    tuple[CandidateBibliographyRenderedEntry, ...],
    bytes,
]:
    source_export = CandidateBibliographyExporter().export(
        request=request.source
    )
    observations_by_citekey: dict[str, list[SourceBibliographyObservation]] = {}
    for source in request.source.sources:
        for observation in source.observations:
            observations_by_citekey.setdefault(
                observation.observed_citekey,
                [],
            ).append(observation)
    entries: list[CandidateBibliographyRenderedEntry] = []
    for citekey in source_export.citekeys:
        observations = observations_by_citekey[citekey]
        entry_type, normalized_fields, rendered_entry = _render_observation(
            observations[0]
        )
        entries.append(
            CandidateBibliographyRenderedEntry(
                citekey=citekey,
                entry_type=entry_type,
                normalized_fields=normalized_fields,
                source_observation_ids=tuple(
                    sorted(item.observation_id for item in observations)
                ),
                rendered_entry=rendered_entry,
            )
        )
    rendered_entries = tuple(entries)
    bibliography = (
        CANDIDATE_BIBLIOGRAPHY_EXPORT_SEPARATOR.join(
            item.rendered_entry for item in rendered_entries
        )
        + b"\n"
    )
    if len(bibliography) > CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES:
        raise CandidateBibliographyRenderError(
            "rendered bibliography exceeds the byte limit"
        )
    return source_export, rendered_entries, bibliography


def _render_observation(
    observation: SourceBibliographyObservation,
) -> tuple[str, tuple[tuple[str, str], ...], bytes]:
    try:
        bibliography = parse_string(observation.verbatim_entry, "bibtex")
        entries = cast(
            Mapping[str, _PybtexEntry],
            bibliography.entries,
        )
    except (PybtexSyntaxError, UnicodeError, ValueError) as error:
        raise CandidateBibliographyRenderError(
            "source observation is not parseable BibTeX"
        ) from error
    if tuple(entries) != (observation.observed_citekey,):
        raise CandidateBibliographyRenderError(
            "source observation does not contain exactly its citekey"
        )
    entry = entries[observation.observed_citekey]
    entry_type = entry.type.lower()
    if _ENTRY_TYPE.fullmatch(entry_type) is None:
        raise CandidateBibliographyRenderError(
            "source observation has an unsupported entry type"
        )
    fields: dict[str, str] = {}
    for name, value in entry.fields.items():
        normalized_name = str(name).lower()
        if normalized_name not in _RENDERABLE_FIELDS:
            raise CandidateBibliographyRenderError(
                f"unsupported BibTeX field: {normalized_name}"
            )
        fields[normalized_name] = _normalize_render_text(
            str(value),
            field=normalized_name,
        )
    for role, persons in entry.persons.items():
        normalized_role = str(role).lower()
        if normalized_role not in _RENDERABLE_PERSON_ROLES:
            raise CandidateBibliographyRenderError(
                f"unsupported BibTeX person role: {normalized_role}"
            )
        if normalized_role in fields:
            raise CandidateBibliographyRenderError(
                f"duplicate normalized BibTeX field: {normalized_role}"
            )
        rendered_persons = tuple(
            _normalize_render_text(str(person), field=normalized_role)
            for person in persons
        )
        if not rendered_persons:
            raise CandidateBibliographyRenderError(
                f"empty BibTeX person role: {normalized_role}"
            )
        fields[normalized_role] = " and ".join(rendered_persons)
    if not fields:
        raise CandidateBibliographyRenderError(
            "candidate entry has no renderable fields"
        )
    normalized_fields = tuple(sorted(fields.items()))
    rendered = _format_rendered_entry(
        citekey=observation.observed_citekey,
        entry_type=entry_type,
        normalized_fields=normalized_fields,
    )
    return entry_type, normalized_fields, rendered


def _normalize_render_text(value: str, *, field: str) -> str:
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in value
    ):
        raise CandidateBibliographyRenderError(
            f"normalized BibTeX field has a control character: {field}"
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise CandidateBibliographyRenderError(
            f"empty normalized BibTeX field: {field}"
        )
    if len(normalized.encode("utf-8")) > 1_000_000:
        raise CandidateBibliographyRenderError(
            f"normalized BibTeX field exceeds the byte limit: {field}"
        )
    if any(character in "{}\\" for character in normalized):
        raise CandidateBibliographyRenderError(
            f"normalized BibTeX field has unsupported braces or backslash: "
            f"{field}"
        )
    return normalized


def _escape_tex(value: str) -> str:
    return "".join(
        _TEX_ESCAPES.get(character, character) for character in value
    )


def _format_rendered_entry(
    *,
    citekey: str,
    entry_type: str,
    normalized_fields: tuple[tuple[str, str], ...],
) -> bytes:
    lines = [f"@{entry_type}{{{citekey},"]
    for index, (name, value) in enumerate(normalized_fields):
        suffix = "," if index + 1 < len(normalized_fields) else ""
        lines.append(f"  {name} = {{{_escape_tex(value)}}}{suffix}")
    lines.append("}")
    return "\n".join(lines).encode("utf-8")


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
