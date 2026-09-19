from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Self

from projectkoios.references.io_limits import (
    bounded_csv_field_size,
    bounded_utf8_size,
)
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import (
    CloudPlaceholderProbe,
    PathLimitError,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
    read_path_bytes,
    validate_citekey,
    validate_relative_path,
)

_GRAPH_SCHEMA_VERSION = 1
_GRAPH_BATCH_SCHEMA_VERSION = 3
_MAX_TEXT_BYTES = 4_096
_MAX_VERBATIM_BYTES = 262_144
_MAX_AUTHORS = 256
_MAX_SOURCE_SIZE = 2**63 - 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")

_SOURCE_FIELDS = (
    "source_observation_id",
    "source_id",
    "asserted_source_revision",
    "source_path",
    "source_sha256",
    "source_byte_size",
)
_CANDIDATE_FIELDS = (
    "candidate_id",
    "source_observation_id",
    "source_locator",
    "verbatim_entry",
    "verbatim_identifier",
    "verbatim_title",
    "verbatim_authors",
    "proposed_citekey",
    "proposed_container_or_type",
    "proposed_title",
    "proposed_authors_json",
    "proposed_year",
    "proposed_doi",
)
_EDGE_FIELDS = (
    "edge_id",
    "source_observation_id",
    "target_candidate_id",
    "relation",
    "source_locator",
)


class CitationGraphError(ValueError):
    """Raised when graph evidence is malformed, orphaned, or unbounded."""


class CitationGraphLimitError(CitationGraphError):
    """Typed graph-limit diagnostic that cannot imply absent citations."""

    code = "citation-graph-limit-exceeded"
    coverage_status = "incomplete"

    def __init__(
        self,
        *,
        resource: str,
        limit_name: str,
        limit: int,
        observed: int,
        limits: GraphImportLimits,
    ) -> None:
        self.resource = resource
        self.limit_name = limit_name
        self.limit = limit
        self.observed = observed
        self.limits = limits
        description = (
            "text byte limit"
            if limit_name in {"max_text_bytes", "max_verbatim_bytes"}
            else "total byte limit"
            if limit_name == "max_total_bytes"
            else "byte limit"
            if limit_name == "max_file_bytes"
            else limit_name
        )
        super().__init__(
            f"{resource} exceeds {description}: observed {observed}, "
            f"limit {limit}; coverage remains incomplete"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "coverage_status": self.coverage_status,
            "resource": self.resource,
            "limit_name": self.limit_name,
            "limit": self.limit,
            "observed": self.observed,
            "effective_limits": asdict(self.limits),
            "effective_limits_id": self.limits.evidence_id,
        }

    def to_json(self) -> str:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


@dataclass(frozen=True)
class GraphImportLimits:
    """Caller-tightenable limits for one three-file direct graph import."""

    max_file_bytes: int = 2_000_000
    max_total_bytes: int = 4_000_000
    max_sources: int = 128
    max_candidates: int = 10_000
    max_edges: int = 10_000
    max_breadth_per_source: int = 2_000
    max_text_bytes: int = _MAX_TEXT_BYTES
    max_verbatim_bytes: int = _MAX_VERBATIM_BYTES
    max_json_depth: int = 64

    def __post_init__(self) -> None:
        hard_limits = {
            "max_file_bytes": 2_000_000,
            "max_total_bytes": 4_000_000,
            "max_sources": 128,
            "max_candidates": 10_000,
            "max_edges": 10_000,
            "max_breadth_per_source": 2_000,
            "max_text_bytes": _MAX_TEXT_BYTES,
            "max_verbatim_bytes": _MAX_VERBATIM_BYTES,
            "max_json_depth": 64,
        }
        for field, hard_limit in hard_limits.items():
            value = getattr(self, field)
            if type(value) is not int or not 0 < value <= hard_limit:
                raise CitationGraphError(
                    f"{field} must be a positive integer no greater than "
                    f"{hard_limit}"
                )

    @property
    def evidence_id(self) -> str:
        rendered = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return (
            "graph-import-limits:sha256:" + hashlib.sha256(rendered).hexdigest()
        )


@dataclass(frozen=True)
class CitationSourceObservation:
    """An exact parent source/blob identity, without bibliographic authority."""

    schema_version: int
    authority_kind: str
    source_id: str
    asserted_source_revision: str | None
    source_path: str
    source_sha256: str
    source_byte_size: int
    source_observation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _GRAPH_SCHEMA_VERSION:
            raise CitationGraphError("unsupported graph source schema version")
        if self.authority_kind != "citation-source-observation":
            raise CitationGraphError("unsupported graph source authority kind")
        _bounded(self.source_id, field="source_id")
        _optional_bounded(
            self.asserted_source_revision,
            field="asserted_source_revision",
        )
        validate_relative_path(self.source_path, field="source_path")
        _sha256(self.source_sha256, field="source_sha256")
        if (
            type(self.source_byte_size) is not int
            or not 0 < self.source_byte_size <= _MAX_SOURCE_SIZE
        ):
            raise CitationGraphError(
                "source_byte_size must be a positive signed 64-bit integer"
            )
        expected = self.identity_for(
            source_id=self.source_id,
            asserted_source_revision=self.asserted_source_revision,
            source_path=self.source_path,
            source_sha256=self.source_sha256,
            source_byte_size=self.source_byte_size,
        )
        if self.source_observation_id != expected:
            raise CitationGraphError(
                "graph source observation identity does not match its evidence"
            )

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        asserted_source_revision: str | None,
        source_path: str,
        source_sha256: str,
        source_byte_size: int,
    ) -> Self:
        identity = cls.identity_for(
            source_id=source_id,
            asserted_source_revision=asserted_source_revision,
            source_path=source_path,
            source_sha256=source_sha256,
            source_byte_size=source_byte_size,
        )
        return cls(
            schema_version=_GRAPH_SCHEMA_VERSION,
            authority_kind="citation-source-observation",
            source_id=source_id,
            asserted_source_revision=asserted_source_revision,
            source_path=source_path,
            source_sha256=source_sha256,
            source_byte_size=source_byte_size,
            source_observation_id=identity,
        )

    @staticmethod
    def identity_for(
        *,
        source_id: str,
        asserted_source_revision: str | None,
        source_path: str,
        source_sha256: str,
        source_byte_size: int,
    ) -> str:
        return _stable_id(
            "citation-source",
            {
                "schema_version": _GRAPH_SCHEMA_VERSION,
                "authority_kind": "citation-source-observation",
                "source_id": source_id,
                "asserted_source_revision": asserted_source_revision,
                "source_path": source_path,
                "source_sha256": source_sha256,
                "source_byte_size": source_byte_size,
            },
        )

    def to_json(self) -> str:
        return _pretty_json(self)

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="citation source observation")
        expected = {
            "schema_version",
            "authority_kind",
            "source_id",
            "asserted_source_revision",
            "source_path",
            "source_sha256",
            "source_byte_size",
            "source_observation_id",
        }
        _exact_fields(data, expected, label="citation source observation")
        revision = _optional_string(
            data["asserted_source_revision"],
            field="asserted_source_revision",
        )
        value = cls(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_string(
                data["authority_kind"], field="authority_kind"
            ),
            source_id=_string(data["source_id"], field="source_id"),
            asserted_source_revision=revision,
            source_path=_string(data["source_path"], field="source_path"),
            source_sha256=_string(data["source_sha256"], field="source_sha256"),
            source_byte_size=_integer(
                data["source_byte_size"], field="source_byte_size"
            ),
            source_observation_id=_string(
                data["source_observation_id"],
                field="source_observation_id",
            ),
        )
        if value.to_json() != text:
            raise CitationGraphError(
                "citation source serialization is not canonical"
            )
        return value


@dataclass(frozen=True)
class CitationCandidate:
    """Source-verbatim entry evidence plus a non-authoritative proposal."""

    schema_version: int
    authority_kind: str
    lifecycle_status: str
    proposal_status: str
    source_observation_id: str
    source_locator: str
    verbatim_entry: str | None
    verbatim_identifier: str | None
    verbatim_title: str | None
    verbatim_authors: str | None
    proposed_citekey: str | None
    proposed_container_or_type: str | None
    proposed_title: str | None
    proposed_authors: tuple[str, ...]
    proposed_year: str | None
    proposed_doi: str | None
    candidate_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _GRAPH_SCHEMA_VERSION:
            raise CitationGraphError(
                "unsupported graph candidate schema version"
            )
        if self.authority_kind != "citation-discovery-candidate":
            raise CitationGraphError(
                "unsupported graph candidate authority kind"
            )
        if self.lifecycle_status != "unaccepted-candidate":
            raise CitationGraphError("graph candidate cannot claim acceptance")
        if self.proposal_status != "unaccepted-normalized-proposal":
            raise CitationGraphError(
                "normalized graph metadata must remain an unaccepted proposal"
            )
        _content_id(
            self.source_observation_id,
            prefix="citation-source",
            field="source_observation_id",
        )
        _bounded(self.source_locator, field="source_locator")
        _optional_bounded(
            self.verbatim_entry,
            field="verbatim_entry",
            max_bytes=_MAX_VERBATIM_BYTES,
        )
        for field, value in (
            ("verbatim_identifier", self.verbatim_identifier),
            ("verbatim_title", self.verbatim_title),
            ("verbatim_authors", self.verbatim_authors),
            (
                "proposed_container_or_type",
                self.proposed_container_or_type,
            ),
            ("proposed_title", self.proposed_title),
            ("proposed_year", self.proposed_year),
            ("proposed_doi", self.proposed_doi),
        ):
            _optional_bounded(value, field=field)
        if self.proposed_citekey is not None:
            validate_citekey(
                self.proposed_citekey,
                field="proposed citekey",
            )
        if not isinstance(self.proposed_authors, tuple) or (
            len(self.proposed_authors) > _MAX_AUTHORS
        ):
            raise CitationGraphError("proposed_authors must be a bounded tuple")
        for author in self.proposed_authors:
            _bounded(author, field="proposed author")
        if normalize_doi(self.proposed_doi) != self.proposed_doi:
            raise CitationGraphError("proposed DOI must be normalized")
        if not any(
            value is not None
            for value in (
                self.verbatim_entry,
                self.verbatim_identifier,
                self.verbatim_title,
                self.verbatim_authors,
            )
        ):
            raise CitationGraphError(
                "graph candidate requires source-verbatim entry evidence"
            )
        expected = self.identity_for(
            source_observation_id=self.source_observation_id,
            source_locator=self.source_locator,
        )
        if self.candidate_id != expected:
            raise CitationGraphError(
                "graph candidate identity does not match source and locator"
            )

    @classmethod
    def create(
        cls,
        *,
        source_observation_id: str,
        source_locator: str,
        verbatim_entry: str | None = None,
        verbatim_identifier: str | None = None,
        verbatim_title: str | None = None,
        verbatim_authors: str | None = None,
        proposed_citekey: str | None = None,
        proposed_container_or_type: str | None = None,
        proposed_title: str | None = None,
        proposed_authors: tuple[str, ...] = (),
        proposed_year: str | None = None,
        proposed_doi: str | None = None,
    ) -> Self:
        return cls(
            schema_version=_GRAPH_SCHEMA_VERSION,
            authority_kind="citation-discovery-candidate",
            lifecycle_status="unaccepted-candidate",
            proposal_status="unaccepted-normalized-proposal",
            source_observation_id=source_observation_id,
            source_locator=source_locator,
            verbatim_entry=verbatim_entry,
            verbatim_identifier=verbatim_identifier,
            verbatim_title=verbatim_title,
            verbatim_authors=verbatim_authors,
            proposed_citekey=proposed_citekey,
            proposed_container_or_type=proposed_container_or_type,
            proposed_title=proposed_title,
            proposed_authors=proposed_authors,
            proposed_year=proposed_year,
            proposed_doi=normalize_doi(proposed_doi),
            candidate_id=cls.identity_for(
                source_observation_id=source_observation_id,
                source_locator=source_locator,
            ),
        )

    @staticmethod
    def identity_for(*, source_observation_id: str, source_locator: str) -> str:
        return _stable_id(
            "citation-candidate",
            {
                "schema_version": _GRAPH_SCHEMA_VERSION,
                "authority_kind": "citation-discovery-candidate",
                "source_observation_id": source_observation_id,
                "source_locator": source_locator,
            },
        )

    def to_json(self) -> str:
        return _pretty_json(self)

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="citation candidate")
        expected = {
            "schema_version",
            "authority_kind",
            "lifecycle_status",
            "proposal_status",
            "source_observation_id",
            "source_locator",
            "verbatim_entry",
            "verbatim_identifier",
            "verbatim_title",
            "verbatim_authors",
            "proposed_citekey",
            "proposed_container_or_type",
            "proposed_title",
            "proposed_authors",
            "proposed_year",
            "proposed_doi",
            "candidate_id",
        }
        _exact_fields(data, expected, label="citation candidate")
        raw_authors = data["proposed_authors"]
        if not isinstance(raw_authors, list) or any(
            not isinstance(item, str) for item in raw_authors
        ):
            raise CitationGraphError(
                "proposed_authors must be an array of strings"
            )
        value = cls(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_string(
                data["authority_kind"], field="authority_kind"
            ),
            lifecycle_status=_string(
                data["lifecycle_status"], field="lifecycle_status"
            ),
            proposal_status=_string(
                data["proposal_status"], field="proposal_status"
            ),
            source_observation_id=_string(
                data["source_observation_id"],
                field="source_observation_id",
            ),
            source_locator=_string(
                data["source_locator"], field="source_locator"
            ),
            verbatim_entry=_optional_string(
                data["verbatim_entry"], field="verbatim_entry"
            ),
            verbatim_identifier=_optional_string(
                data["verbatim_identifier"],
                field="verbatim_identifier",
            ),
            verbatim_title=_optional_string(
                data["verbatim_title"], field="verbatim_title"
            ),
            verbatim_authors=_optional_string(
                data["verbatim_authors"], field="verbatim_authors"
            ),
            proposed_citekey=_optional_string(
                data["proposed_citekey"], field="proposed_citekey"
            ),
            proposed_container_or_type=_optional_string(
                data["proposed_container_or_type"],
                field="proposed_container_or_type",
            ),
            proposed_title=_optional_string(
                data["proposed_title"], field="proposed_title"
            ),
            proposed_authors=tuple(raw_authors),
            proposed_year=_optional_string(
                data["proposed_year"], field="proposed_year"
            ),
            proposed_doi=_optional_string(
                data["proposed_doi"], field="proposed_doi"
            ),
            candidate_id=_string(data["candidate_id"], field="candidate_id"),
        )
        if value.to_json() != text:
            raise CitationGraphError(
                "citation candidate serialization is not canonical"
            )
        return value


@dataclass(frozen=True)
class CitationEdge:
    """A direct citation observation; not endorsement or claim support."""

    schema_version: int
    authority_kind: str
    evidence_status: str
    source_observation_id: str
    target_candidate_id: str
    relation: str
    source_locator: str
    edge_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _GRAPH_SCHEMA_VERSION:
            raise CitationGraphError("unsupported citation edge schema version")
        if self.authority_kind != "direct-citation-observation":
            raise CitationGraphError("unsupported citation edge authority kind")
        if self.evidence_status != "source-observed-only":
            raise CitationGraphError(
                "citation edge cannot imply relevance or acceptance"
            )
        _content_id(
            self.source_observation_id,
            prefix="citation-source",
            field="source_observation_id",
        )
        _content_id(
            self.target_candidate_id,
            prefix="citation-candidate",
            field="target_candidate_id",
        )
        if self.relation != "cites":
            raise CitationGraphError("only direct cites edges are supported")
        _bounded(self.source_locator, field="source_locator")
        expected = self.identity_for(
            source_observation_id=self.source_observation_id,
            target_candidate_id=self.target_candidate_id,
            relation=self.relation,
            source_locator=self.source_locator,
        )
        if self.edge_id != expected:
            raise CitationGraphError("citation edge identity does not match")

    @classmethod
    def create(
        cls,
        *,
        source_observation_id: str,
        target_candidate_id: str,
        source_locator: str,
        relation: str = "cites",
    ) -> Self:
        return cls(
            schema_version=_GRAPH_SCHEMA_VERSION,
            authority_kind="direct-citation-observation",
            evidence_status="source-observed-only",
            source_observation_id=source_observation_id,
            target_candidate_id=target_candidate_id,
            relation=relation,
            source_locator=source_locator,
            edge_id=cls.identity_for(
                source_observation_id=source_observation_id,
                target_candidate_id=target_candidate_id,
                relation=relation,
                source_locator=source_locator,
            ),
        )

    @staticmethod
    def identity_for(
        *,
        source_observation_id: str,
        target_candidate_id: str,
        relation: str,
        source_locator: str,
    ) -> str:
        return _stable_id(
            "citation-edge",
            {
                "schema_version": _GRAPH_SCHEMA_VERSION,
                "authority_kind": "direct-citation-observation",
                "source_observation_id": source_observation_id,
                "target_candidate_id": target_candidate_id,
                "relation": relation,
                "source_locator": source_locator,
            },
        )

    def to_json(self) -> str:
        return _pretty_json(self)

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="citation edge")
        expected = {
            "schema_version",
            "authority_kind",
            "evidence_status",
            "source_observation_id",
            "target_candidate_id",
            "relation",
            "source_locator",
            "edge_id",
        }
        _exact_fields(data, expected, label="citation edge")
        value = cls(
            schema_version=_integer(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_string(
                data["authority_kind"], field="authority_kind"
            ),
            evidence_status=_string(
                data["evidence_status"], field="evidence_status"
            ),
            source_observation_id=_string(
                data["source_observation_id"],
                field="source_observation_id",
            ),
            target_candidate_id=_string(
                data["target_candidate_id"],
                field="target_candidate_id",
            ),
            relation=_string(data["relation"], field="relation"),
            source_locator=_string(
                data["source_locator"], field="source_locator"
            ),
            edge_id=_string(data["edge_id"], field="edge_id"),
        )
        if value.to_json() != text:
            raise CitationGraphError(
                "citation edge serialization is not canonical"
            )
        return value


@dataclass(frozen=True)
class CitationGraph:
    """A fully validated, deterministic direct-citation evidence batch."""

    sources: tuple[CitationSourceObservation, ...]
    candidates: tuple[CitationCandidate, ...]
    edges: tuple[CitationEdge, ...]
    effective_limits: GraphImportLimits = GraphImportLimits()
    root_preflights: tuple[RootPreflightEvidence, ...] = dataclass_field(
        default=(),
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_graph(
            sources=self.sources,
            candidates=self.candidates,
            edges=self.edges,
            limits=self.effective_limits,
        )
        aliases = tuple(item.root_alias for item in self.root_preflights)
        if aliases != tuple(sorted(aliases)) or len(aliases) != len(
            set(aliases)
        ):
            raise CitationGraphError(
                "graph root preflights must be alias-sorted and unique"
            )
        if self.sources != tuple(
            sorted(
                self.sources,
                key=lambda item: item.source_observation_id,
            )
        ):
            raise CitationGraphError(
                "graph sources must use deterministic identity order"
            )
        if self.candidates != tuple(
            sorted(self.candidates, key=lambda item: item.candidate_id)
        ):
            raise CitationGraphError(
                "graph candidates must use deterministic identity order"
            )
        if self.edges != tuple(
            sorted(self.edges, key=lambda item: item.edge_id)
        ):
            raise CitationGraphError(
                "graph edges must use deterministic identity order"
            )

    @classmethod
    def create(
        cls,
        *,
        sources: tuple[CitationSourceObservation, ...],
        candidates: tuple[CitationCandidate, ...],
        edges: tuple[CitationEdge, ...],
        limits: GraphImportLimits | None = None,
        root_preflights: tuple[RootPreflightEvidence, ...] = (),
    ) -> Self:
        active_limits = limits or GraphImportLimits()
        _validate_graph(
            sources=sources,
            candidates=candidates,
            edges=edges,
            limits=active_limits,
        )
        return cls(
            sources=tuple(
                sorted(sources, key=lambda item: item.source_observation_id)
            ),
            candidates=tuple(
                sorted(candidates, key=lambda item: item.candidate_id)
            ),
            edges=tuple(sorted(edges, key=lambda item: item.edge_id)),
            effective_limits=active_limits,
            root_preflights=root_preflights,
        )

    def to_json(self) -> str:
        payload = {
            "authority_boundary": (
                "citation-observation-only-no-membership-or-acceptance-authority"
            ),
            "schema_version": _GRAPH_BATCH_SCHEMA_VERSION,
            "coverage_status": "complete",
            "effective_limits": asdict(self.effective_limits),
            "effective_limits_id": self.effective_limits.evidence_id,
            "root_preflights": [asdict(item) for item in self.root_preflights],
            "sources": [json.loads(item.to_json()) for item in self.sources],
            "candidates": [
                json.loads(item.to_json()) for item in self.candidates
            ],
            "edges": [json.loads(item.to_json()) for item in self.edges],
        }
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


def _validate_graph(
    *,
    sources: tuple[CitationSourceObservation, ...],
    candidates: tuple[CitationCandidate, ...],
    edges: tuple[CitationEdge, ...],
    limits: GraphImportLimits,
) -> None:
    if any(not isinstance(item, CitationSourceObservation) for item in sources):
        raise CitationGraphError(
            "sources must contain CitationSourceObservation values"
        )
    if any(not isinstance(item, CitationCandidate) for item in candidates):
        raise CitationGraphError(
            "candidates must contain CitationCandidate values"
        )
    if any(not isinstance(item, CitationEdge) for item in edges):
        raise CitationGraphError("edges must contain CitationEdge values")
    _row_limit("source", len(sources), limits.max_sources, limits=limits)
    _row_limit(
        "candidate", len(candidates), limits.max_candidates, limits=limits
    )
    _row_limit("edge", len(edges), limits.max_edges, limits=limits)
    if not sources and (candidates or edges):
        raise CitationGraphError("graph rows require a source observation")
    if sources and not candidates:
        raise CitationGraphError(
            "nonempty graph sources require candidates and direct edges"
        )
    if not candidates and edges:
        raise CitationGraphError("graph edges require candidate targets")

    source_by_id = _unique_by_id(
        sources,
        id_field="source_observation_id",
        label="source observation",
    )
    candidate_by_id = _unique_by_id(
        candidates,
        id_field="candidate_id",
        label="candidate",
    )
    _unique_by_id(edges, id_field="edge_id", label="edge")

    candidate_slots: set[tuple[str, str]] = set()
    for candidate in candidates:
        if candidate.source_observation_id not in source_by_id:
            raise CitationGraphError(
                f"candidate {candidate.candidate_id} has an orphan source "
                f"observation {candidate.source_observation_id}"
            )
        slot = (candidate.source_observation_id, candidate.source_locator)
        if slot in candidate_slots:
            raise CitationGraphError(
                "multiple candidates claim the same source entry locator"
            )
        candidate_slots.add(slot)

    breadth: dict[str, int] = {}
    edge_targets: set[str] = set()
    edge_sources: set[str] = set()
    for edge in edges:
        if edge.source_observation_id not in source_by_id:
            raise CitationGraphError(
                f"edge {edge.edge_id} has an orphan source observation "
                f"{edge.source_observation_id}"
            )
        target = candidate_by_id.get(edge.target_candidate_id)
        if target is None:
            raise CitationGraphError(
                f"edge {edge.edge_id} has an orphan candidate target "
                f"{edge.target_candidate_id}"
            )
        if (
            target.source_observation_id != edge.source_observation_id
            or target.source_locator != edge.source_locator
        ):
            raise CitationGraphError(
                f"edge {edge.edge_id} source/locator differs from its "
                "candidate evidence"
            )
        if edge.target_candidate_id in edge_targets:
            raise CitationGraphError(
                f"candidate {edge.target_candidate_id} has duplicate edges"
            )
        edge_targets.add(edge.target_candidate_id)
        edge_sources.add(edge.source_observation_id)
        breadth[edge.source_observation_id] = (
            breadth.get(edge.source_observation_id, 0) + 1
        )
    if edge_targets != set(candidate_by_id):
        missing = sorted(set(candidate_by_id) - edge_targets)
        raise CitationGraphError(
            f"graph has candidate rows without direct edges: {missing}"
        )
    if candidates and edge_sources != set(source_by_id):
        missing = sorted(set(source_by_id) - edge_sources)
        raise CitationGraphError(
            f"graph has source observations without direct edges: {missing}"
        )
    oversized = sorted(
        source_id
        for source_id, count in breadth.items()
        if count > limits.max_breadth_per_source
    )
    if oversized:
        raise CitationGraphLimitError(
            resource="citation graph breadth",
            limit_name="max_breadth_per_source",
            limit=limits.max_breadth_per_source,
            observed=max(breadth[source_id] for source_id in oversized),
            limits=limits,
        )


def load_candidate_graph(
    sources_path: Path,
    nodes_path: Path,
    edges_path: Path,
    *,
    sources_storage_class: RootStorageClass,
    nodes_storage_class: RootStorageClass,
    edges_storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: GraphImportLimits | None = None,
) -> CitationGraph:
    """Load and atomically validate three bounded graph CSV files."""
    active_limits = limits or GraphImportLimits()
    inputs = (
        (
            sources_path,
            "citation sources",
            "citation-sources",
            sources_storage_class,
            _SOURCE_FIELDS,
        ),
        (
            nodes_path,
            "citation candidates",
            "citation-candidates",
            nodes_storage_class,
            _CANDIDATE_FIELDS,
        ),
        (
            edges_path,
            "citation edges",
            "citation-edges",
            edges_storage_class,
            _EDGE_FIELDS,
        ),
    )
    root_preflights = tuple(
        sorted(
            (
                authorize_root_preflight(
                    root_alias=alias,
                    storage_class=storage_class,
                    placeholder_probe=placeholder_probe,
                )
                for _, _, alias, storage_class, _ in inputs
            ),
            key=lambda item: item.root_alias,
        )
    )
    contents: list[tuple[str, tuple[dict[str, str], ...]]] = []
    total_bytes = 0
    for path, label, alias, storage_class, expected_fields in inputs:
        try:
            raw = read_path_bytes(
                path,
                label=label,
                root_alias=alias,
                storage_class=storage_class,
                placeholder_probe=placeholder_probe,
                max_bytes=active_limits.max_file_bytes,
            )
        except PathLimitError as error:
            raise CitationGraphLimitError(
                resource=label,
                limit_name="max_file_bytes",
                limit=active_limits.max_file_bytes,
                observed=error.observed,
                limits=active_limits,
            ) from error
        except (OSError, UnicodeError, ValueError) as error:
            raise CitationGraphError(
                f"cannot read bounded {label} CSV: {error}"
            ) from error
        total_bytes += len(raw)
        if total_bytes > active_limits.max_total_bytes:
            raise CitationGraphLimitError(
                resource="citation graph files",
                limit_name="max_total_bytes",
                limit=active_limits.max_total_bytes,
                observed=total_bytes,
                limits=active_limits,
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CitationGraphError(f"{label} CSV is not UTF-8") from error
        row_limit = {
            "citation sources": active_limits.max_sources,
            "citation candidates": active_limits.max_candidates,
            "citation edges": active_limits.max_edges,
        }[label]
        rows = _csv_rows(
            text,
            expected_fields=expected_fields,
            label=label,
            max_rows=row_limit,
            limits=active_limits,
        )
        contents.append((label, rows))

    source_rows = contents[0][1]
    candidate_rows = contents[1][1]
    edge_rows = contents[2][1]
    _row_limit(
        "source",
        len(source_rows),
        active_limits.max_sources,
        limits=active_limits,
    )
    _row_limit(
        "candidate",
        len(candidate_rows),
        active_limits.max_candidates,
        limits=active_limits,
    )
    _row_limit(
        "edge",
        len(edge_rows),
        active_limits.max_edges,
        limits=active_limits,
    )

    sources = tuple(
        _source_from_csv(row, limits=active_limits) for row in source_rows
    )
    candidates = tuple(
        _candidate_from_csv(row, limits=active_limits) for row in candidate_rows
    )
    edges = tuple(
        _edge_from_csv(row, limits=active_limits) for row in edge_rows
    )
    return CitationGraph.create(
        sources=sources,
        candidates=candidates,
        edges=edges,
        limits=active_limits,
        root_preflights=root_preflights,
    )


def _source_from_csv(
    row: dict[str, str], *, limits: GraphImportLimits
) -> CitationSourceObservation:
    _check_csv_text_limits(row, limits=limits)
    byte_size = _canonical_positive_int(
        row["source_byte_size"], field="source_byte_size"
    )
    value = CitationSourceObservation.create(
        source_id=row["source_id"],
        asserted_source_revision=row["asserted_source_revision"] or None,
        source_path=row["source_path"],
        source_sha256=row["source_sha256"],
        source_byte_size=byte_size,
    )
    if row["source_observation_id"] != value.source_observation_id:
        raise CitationGraphError(
            "source_observation_id does not match its exact source evidence"
        )
    return value


def _candidate_from_csv(
    row: dict[str, str], *, limits: GraphImportLimits
) -> CitationCandidate:
    _check_csv_text_limits(
        row,
        limits=limits,
        verbatim_fields=frozenset({"verbatim_entry"}),
    )
    _check_json_nesting(
        row["proposed_authors_json"],
        limits=limits,
        resource="proposed_authors_json",
    )
    try:
        authors_value = json.loads(row["proposed_authors_json"])
    except json.JSONDecodeError as error:
        raise CitationGraphError(
            "proposed_authors_json must be valid JSON"
        ) from error
    if not isinstance(authors_value, list) or any(
        not isinstance(item, str) for item in authors_value
    ):
        raise CitationGraphError(
            "proposed_authors_json must be an array of strings"
        )
    candidate = CitationCandidate.create(
        source_observation_id=row["source_observation_id"],
        source_locator=row["source_locator"],
        verbatim_entry=row["verbatim_entry"] or None,
        verbatim_identifier=row["verbatim_identifier"] or None,
        verbatim_title=row["verbatim_title"] or None,
        verbatim_authors=row["verbatim_authors"] or None,
        proposed_citekey=row["proposed_citekey"] or None,
        proposed_container_or_type=(row["proposed_container_or_type"] or None),
        proposed_title=row["proposed_title"] or None,
        proposed_authors=tuple(authors_value),
        proposed_year=row["proposed_year"] or None,
        proposed_doi=row["proposed_doi"] or None,
    )
    if row["proposed_doi"] and candidate.proposed_doi != row["proposed_doi"]:
        raise CitationGraphError(
            "proposed_doi must already be normalized; preserve the source "
            "form in verbatim_identifier"
        )
    if row["candidate_id"] != candidate.candidate_id:
        raise CitationGraphError(
            "candidate_id does not match source observation and locator"
        )
    return candidate


def _edge_from_csv(
    row: dict[str, str], *, limits: GraphImportLimits
) -> CitationEdge:
    _check_csv_text_limits(row, limits=limits)
    value = CitationEdge.create(
        source_observation_id=row["source_observation_id"],
        target_candidate_id=row["target_candidate_id"],
        relation=row["relation"],
        source_locator=row["source_locator"],
    )
    if row["edge_id"] != value.edge_id:
        raise CitationGraphError("edge_id does not match edge evidence")
    return value


def _csv_rows(
    text: str,
    *,
    expected_fields: tuple[str, ...],
    label: str,
    max_rows: int,
    limits: GraphImportLimits,
) -> tuple[dict[str, str], ...]:
    if not text or "\x00" in text:
        raise CitationGraphError(f"{label} CSV is empty or contains NUL")
    try:
        with bounded_csv_field_size(limits.max_verbatim_bytes):
            reader = csv.DictReader(
                io.StringIO(text, newline=""),
                strict=True,
            )
            if tuple(reader.fieldnames or ()) != expected_fields:
                raise CitationGraphError(
                    f"{label} CSV header must be exactly {expected_fields!r}"
                )
            result: list[dict[str, str]] = []
            for row_number, row in enumerate(reader, start=2):
                observed_rows = row_number - 1
                if observed_rows > max_rows:
                    raise CitationGraphLimitError(
                        resource=f"{label} CSV",
                        limit_name="max_rows",
                        limit=max_rows,
                        observed=observed_rows,
                        limits=limits,
                    )
                if None in row or any(value is None for value in row.values()):
                    raise CitationGraphError(
                        f"{label} CSV row {row_number} has the wrong field "
                        "count"
                    )
                result.append({key: str(value) for key, value in row.items()})
            return tuple(result)
    except csv.Error as error:
        if "field larger than field limit" in str(error):
            raise CitationGraphLimitError(
                resource=f"{label} CSV field",
                limit_name="max_verbatim_bytes",
                limit=limits.max_verbatim_bytes,
                observed=limits.max_verbatim_bytes + 1,
                limits=limits,
            ) from error
        raise CitationGraphError(
            f"{label} CSV is malformed: {error}"
        ) from error


def _check_csv_text_limits(
    row: dict[str, str],
    *,
    limits: GraphImportLimits,
    verbatim_fields: frozenset[str] = frozenset(),
) -> None:
    for field, value in row.items():
        maximum = (
            limits.max_verbatim_bytes
            if field in verbatim_fields
            else limits.max_text_bytes
        )
        observed = bounded_utf8_size(value, max_bytes=maximum)
        if observed > maximum:
            raise CitationGraphLimitError(
                resource=f"citation graph field {field}",
                limit_name=(
                    "max_verbatim_bytes"
                    if field in verbatim_fields
                    else "max_text_bytes"
                ),
                limit=maximum,
                observed=observed,
                limits=limits,
            )


def _check_json_nesting(
    text: str,
    *,
    limits: GraphImportLimits,
    resource: str,
) -> None:
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character in "[{":
            depth += 1
            if depth > limits.max_json_depth:
                raise CitationGraphLimitError(
                    resource=resource,
                    limit_name="max_json_depth",
                    limit=limits.max_json_depth,
                    observed=depth,
                    limits=limits,
                )
        elif character in "]}":
            depth = max(0, depth - 1)


def _unique_by_id[T](
    values: tuple[T, ...], *, id_field: str, label: str
) -> dict[str, T]:
    result: dict[str, T] = {}
    for value in values:
        identity = str(getattr(value, id_field))
        if identity in result:
            raise CitationGraphError(
                f"duplicate {label} identity in one graph batch: {identity}"
            )
        result[identity] = value
    return result


def _row_limit(
    label: str,
    count: int,
    maximum: int,
    *,
    limits: GraphImportLimits,
) -> None:
    if count > maximum:
        raise CitationGraphLimitError(
            resource=f"citation graph {label} rows",
            limit_name="max_rows",
            limit=maximum,
            observed=count,
            limits=limits,
        )


def _bounded(
    value: object, *, field: str, max_bytes: int = _MAX_TEXT_BYTES
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise CitationGraphError(
            f"{field} must be bounded non-empty UTF-8 text"
        )
    return value


def _optional_bounded(
    value: object,
    *,
    field: str,
    max_bytes: int = _MAX_TEXT_BYTES,
) -> str | None:
    if value is None:
        return None
    return _bounded(value, field=field, max_bytes=max_bytes)


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CitationGraphError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _content_id(value: object, *, prefix: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or _CONTENT_ID.fullmatch(value) is None
        or not value.startswith(f"{prefix}:sha256:")
    ):
        raise CitationGraphError(f"{field} is not a supported content identity")
    return value


def _canonical_positive_int(value: str, *, field: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise CitationGraphError(
            f"{field} must be a positive integer"
        ) from error
    if str(parsed) != value or parsed <= 0:
        raise CitationGraphError(
            f"{field} must be a canonical positive integer"
        )
    return parsed


def _stable_id(kind: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(encoded).hexdigest()}"


def _pretty_json(
    value: CitationSourceObservation | CitationCandidate | CitationEdge,
) -> str:
    return (
        json.dumps(
            asdict(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _canonical_object(text: str, *, label: str) -> dict[str, object]:
    limits = GraphImportLimits()
    observed_bytes = bounded_utf8_size(
        text,
        max_bytes=limits.max_file_bytes,
    )
    if observed_bytes > limits.max_file_bytes:
        raise CitationGraphLimitError(
            resource=f"{label} JSON",
            limit_name="max_file_bytes",
            limit=limits.max_file_bytes,
            observed=observed_bytes,
            limits=limits,
        )
    _check_json_nesting(text, limits=limits, resource=f"{label} JSON")
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as error:
        raise CitationGraphError(f"{label} JSON is malformed") from error
    if not isinstance(value, dict):
        raise CitationGraphError(f"{label} JSON must be an object")
    return value


def _exact_fields(
    value: dict[str, object], expected: set[str], *, label: str
) -> None:
    if set(value) != expected:
        raise CitationGraphError(
            f"{label} JSON fields are incomplete or unknown"
        )


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CitationGraphError(f"{field} must be a string")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _integer(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise CitationGraphError(f"{field} must be an integer")
    return value
