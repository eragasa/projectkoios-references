from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from typing import Any

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
    SourceBibliographyObservation,
    replay_identity_decisions,
)
from projectkoios.references.path_safety import (
    validate_citekey,
    validate_relative_path,
)

CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID = (
    "projectkoios.references.citation-source-document-link"
)
CITATION_DOCUMENT_PROJECTION_CONTRACT_ID = (
    "projectkoios.references.citation-document-projection"
)
CITATION_SOURCE_DOCUMENT_LINKER_NAME = (
    "projectkoios-references-citation-source-document-linker"
)
CITATION_DOCUMENT_PROJECTOR_NAME = (
    "projectkoios-references-citation-document-projector"
)

CITATION_DOCUMENT_MAX_OCCURRENCES = 10_000
CITATION_DOCUMENT_MAX_KEYS = 10_000
CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES = 10_000
CITATION_DOCUMENT_MAX_SOURCE_GAPS = 10_000
CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS = 10_000
CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY = 256
CITATION_DOCUMENT_MAX_LINKS = 20_000
CITATION_DOCUMENT_MAX_ID_BYTES = 512
CITATION_DOCUMENT_MAX_TEXT_BYTES = 4_096


class _CitationDocumentContract:
    _DIGEST = re.compile(r"^[0-9a-f]{64}$")
    _TARGET_IDS = {
        "snapshot": re.compile(r"^citation-snapshot:[0-9a-f]{64}$"),
        "occurrence": re.compile(r"^citation-occurrence:[0-9a-f]{64}$"),
        "group": re.compile(r"^citation-group:[0-9a-f]{64}$"),
        "entry": re.compile(r"^citation-entry:[0-9a-f]{64}$"),
        "gap": re.compile(r"^citation-gap:[0-9a-f]{64}$"),
    }
    _CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")

    @classmethod
    def stable_id(cls, prefix: str, payload: object) -> str:
        canonical = json.dumps(
            cls.json_value(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"{prefix}:sha256:{hashlib.sha256(canonical).hexdigest()}"

    @classmethod
    def json_value(cls, value: object) -> object:
        if isinstance(value, StrEnum):
            return value.value
        if is_dataclass(value) and not isinstance(value, type):
            return {
                item.name: cls.json_value(getattr(value, item.name))
                for item in fields(value)
            }
        if isinstance(value, tuple):
            return [cls.json_value(item) for item in value]
        if isinstance(value, list):
            return [cls.json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): cls.json_value(item) for key, item in value.items()
            }
        return value

    @classmethod
    def bounded_text(
        cls,
        value: object,
        *,
        field_name: str,
        maximum: int = CITATION_DOCUMENT_MAX_TEXT_BYTES,
    ) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} must be bounded non-empty text")
        if len(value) > maximum:
            raise ValueError(f"{field_name} exceeds the text limit")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} must be UTF-8 encodable") from error
        if (
            len(encoded) > maximum
            or value != value.strip()
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in value
            )
        ):
            raise ValueError(f"{field_name} is malformed")
        return value

    @classmethod
    def opaque_id(cls, value: object, *, field_name: str) -> str:
        return cls.bounded_text(
            value,
            field_name=field_name,
            maximum=CITATION_DOCUMENT_MAX_ID_BYTES,
        )

    @classmethod
    def target_id(
        cls,
        value: object,
        *,
        kind: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str) or not cls._TARGET_IDS[kind].fullmatch(
            value
        ):
            raise ValueError(f"{field_name} is invalid")
        return value

    @classmethod
    def content_id(cls, value: object, *, field_name: str) -> str:
        if not isinstance(value, str) or not cls._CONTENT_ID.fullmatch(value):
            raise ValueError(f"{field_name} is invalid")
        return value

    @staticmethod
    def sequential_indexes(
        values: tuple[Any, ...],
        *,
        attribute: str,
        field_name: str,
    ) -> None:
        if tuple(getattr(item, attribute) for item in values) != tuple(
            range(len(values))
        ):
            raise ValueError(f"{field_name} indexes are not canonical")

    @classmethod
    def validate_identity(
        cls,
        *,
        actual: str,
        prefix: str,
        payload: object,
        field_name: str,
    ) -> None:
        if actual != cls.stable_id(prefix, payload):
            raise ValueError(f"{field_name} does not match content")


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationContentIdentity(DataObjectModel):
    """Exact bounded content identity supplied by the target owner."""

    algorithm: str
    digest: str
    byte_count: int

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValueError("citation content algorithm must be sha256")
        if not _CitationDocumentContract._DIGEST.fullmatch(self.digest):
            raise ValueError("citation content digest is invalid")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("citation content byte count is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceLocator(DataObjectModel):
    """Source-relative citation location with no retained excerpt."""

    source_path: str
    source_content_identity: CitationContentIdentity
    include_index: int
    byte_start: int
    byte_end: int
    line: int
    column: int

    def __post_init__(self) -> None:
        validate_relative_path(self.source_path, field="citation source path")
        if len(self.source_path.encode("utf-8")) > (
            CITATION_DOCUMENT_MAX_TEXT_BYTES
        ):
            raise ValueError("citation source path exceeds the text limit")
        if not isinstance(
            self.source_content_identity,
            CitationContentIdentity,
        ):
            raise TypeError(
                "source_content_identity must be a CitationContentIdentity"
            )
        if type(self.include_index) is not int or self.include_index < 0:
            raise ValueError("citation include index is invalid")
        if (
            type(self.byte_start) is not int
            or type(self.byte_end) is not int
            or self.byte_start < 0
            or self.byte_end <= self.byte_start
            or self.byte_end > self.source_content_identity.byte_count
        ):
            raise ValueError("citation byte range is invalid")
        if type(self.line) is not int or self.line < 1:
            raise ValueError("citation source line is invalid")
        if type(self.column) is not int or self.column < 1:
            raise ValueError("citation source column is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationTargetOccurrence(DataObjectModel):
    """One exact literal-key occurrence from a complete target snapshot."""

    occurrence_id: str
    occurrence_index: int
    call_index: int
    key_index: int
    key: str
    origin: str
    locator: CitationSourceLocator
    bibliography_entry_index: int | None
    todo_marker_index: int | None

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.occurrence_id,
            kind="occurrence",
            field_name="citation occurrence identity",
        )
        for value, field_name in (
            (self.occurrence_index, "occurrence_index"),
            (self.call_index, "call_index"),
            (self.key_index, "key_index"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        validate_citekey(self.key, field="literal citation key")
        if self.origin not in {"direct", "citation_todo_generated"}:
            raise ValueError("citation occurrence origin is invalid")
        if not isinstance(self.locator, CitationSourceLocator):
            raise TypeError("locator must be a CitationSourceLocator")
        if self.bibliography_entry_index is not None and (
            type(self.bibliography_entry_index) is not int
            or self.bibliography_entry_index < 0
        ):
            raise ValueError("bibliography entry index is invalid")
        if self.origin == "direct":
            if self.todo_marker_index is not None:
                raise ValueError("direct citation cannot bind a todo marker")
        elif (
            type(self.todo_marker_index) is not int
            or self.todo_marker_index < 0
        ):
            raise ValueError("generated citation requires a todo marker index")


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationTargetGroup(DataObjectModel):
    """All target occurrence indexes for one exact literal key."""

    group_id: str
    group_index: int
    key: str
    occurrence_indexes: tuple[int, ...]
    direct_occurrence_count: int
    generated_occurrence_count: int
    bibliography_entry_index: int | None

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.group_id,
            kind="group",
            field_name="citation group identity",
        )
        if type(self.group_index) is not int or self.group_index < 0:
            raise ValueError("citation group index is invalid")
        validate_citekey(self.key, field="citation group key")
        if (
            not isinstance(self.occurrence_indexes, tuple)
            or not self.occurrence_indexes
            or any(
                type(item) is not int or item < 0
                for item in self.occurrence_indexes
            )
            or self.occurrence_indexes
            != tuple(sorted(set(self.occurrence_indexes)))
        ):
            raise ValueError("group occurrence indexes are not canonical")
        for value, field_name in (
            (self.direct_occurrence_count, "direct occurrence count"),
            (self.generated_occurrence_count, "generated occurrence count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} is invalid")
        if self.direct_occurrence_count + self.generated_occurrence_count != (
            len(self.occurrence_indexes)
        ):
            raise ValueError("citation group counts conflict")
        if self.bibliography_entry_index is not None and (
            type(self.bibliography_entry_index) is not int
            or self.bibliography_entry_index < 0
        ):
            raise ValueError("group bibliography entry index is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationTargetBibliographyEntry(DataObjectModel):
    """One target bibliography entry with an optional owner binding."""

    entry_id: str
    entry_index: int
    key: str
    entry_type: str
    locator: CitationSourceLocator
    entry_content_identity: CitationContentIdentity
    source_bibliography_observation_id: str | None = None

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.entry_id,
            kind="entry",
            field_name="citation bibliography entry identity",
        )
        if type(self.entry_index) is not int or self.entry_index < 0:
            raise ValueError("citation bibliography entry index is invalid")
        validate_citekey(self.key, field="bibliography entry key")
        _CitationDocumentContract.bounded_text(
            self.entry_type,
            field_name="bibliography entry type",
        )
        if not isinstance(self.locator, CitationSourceLocator):
            raise TypeError("entry locator must be a CitationSourceLocator")
        if not isinstance(
            self.entry_content_identity,
            CitationContentIdentity,
        ):
            raise TypeError(
                "entry_content_identity must be a CitationContentIdentity"
            )
        if self.source_bibliography_observation_id is not None:
            _CitationDocumentContract.content_id(
                self.source_bibliography_observation_id,
                field_name="source bibliography observation identity",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationTargetSourceGap(DataObjectModel):
    """A target-owned citation placeholder without an invented key."""

    source_gap_id: str
    source_gap_index: int
    locator: CitationSourceLocator
    reason: str
    placeholder_identifier: str

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.source_gap_id,
            kind="gap",
            field_name="citation source-gap identity",
        )
        if type(self.source_gap_index) is not int or self.source_gap_index < 0:
            raise ValueError("citation source-gap index is invalid")
        if not isinstance(self.locator, CitationSourceLocator):
            raise TypeError(
                "source-gap locator must be a CitationSourceLocator"
            )
        if self.reason != "placeholder_identifier":
            raise ValueError("citation source-gap reason is invalid")
        _CitationDocumentContract.bounded_text(
            self.placeholder_identifier,
            field_name="placeholder identifier",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationTargetSnapshot(DataObjectModel):
    """Bounded neutral projection of one complete target-owned snapshot."""

    snapshot_id: str
    bibliography_source_path: str
    bibliography_content_identity: CitationContentIdentity
    occurrences: tuple[CitationTargetOccurrence, ...]
    groups: tuple[CitationTargetGroup, ...]
    bibliography_entries: tuple[CitationTargetBibliographyEntry, ...]
    source_gaps: tuple[CitationTargetSourceGap, ...]
    missing_keys: tuple[str, ...]
    duplicate_keys: tuple[str, ...]
    uncited_keys: tuple[str, ...]
    target_projection_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.snapshot_id,
            kind="snapshot",
            field_name="target citation snapshot identity",
        )
        validate_relative_path(
            self.bibliography_source_path,
            field="bibliography source path",
        )
        if not isinstance(
            self.bibliography_content_identity,
            CitationContentIdentity,
        ):
            raise TypeError(
                "bibliography_content_identity must be a "
                "CitationContentIdentity"
            )
        typed_values = (
            (
                self.occurrences,
                CitationTargetOccurrence,
                "target occurrences",
                CITATION_DOCUMENT_MAX_OCCURRENCES,
            ),
            (
                self.groups,
                CitationTargetGroup,
                "target groups",
                CITATION_DOCUMENT_MAX_KEYS,
            ),
            (
                self.bibliography_entries,
                CitationTargetBibliographyEntry,
                "target bibliography entries",
                CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES,
            ),
            (
                self.source_gaps,
                CitationTargetSourceGap,
                "target source gaps",
                CITATION_DOCUMENT_MAX_SOURCE_GAPS,
            ),
        )
        for values, expected, field_name, maximum in typed_values:
            if (
                not isinstance(values, tuple)
                or len(values) > maximum
                or any(not isinstance(item, expected) for item in values)
            ):
                raise TypeError(f"{field_name} are invalid")
        _CitationDocumentContract.sequential_indexes(
            self.occurrences,
            attribute="occurrence_index",
            field_name="target occurrences",
        )
        _CitationDocumentContract.sequential_indexes(
            self.bibliography_entries,
            attribute="entry_index",
            field_name="target bibliography entries",
        )
        _CitationDocumentContract.sequential_indexes(
            self.source_gaps,
            attribute="source_gap_index",
            field_name="target source gaps",
        )
        group_keys = tuple(item.key for item in self.groups)
        if (
            group_keys != tuple(sorted(group_keys))
            or len(group_keys) != len(set(group_keys))
            or tuple(item.group_index for item in self.groups)
            != tuple(range(len(self.groups)))
        ):
            raise ValueError("target citation groups are not canonical")
        self._validate_group_occurrences()
        self._validate_bibliography()
        self._validate_key_sets()
        self._validate_external_ids()
        object.__setattr__(
            self,
            "target_projection_id",
            self.identity_for(
                snapshot_id=self.snapshot_id,
                bibliography_source_path=self.bibliography_source_path,
                bibliography_content_identity=(
                    self.bibliography_content_identity
                ),
                occurrences=self.occurrences,
                groups=self.groups,
                bibliography_entries=self.bibliography_entries,
                source_gaps=self.source_gaps,
                missing_keys=self.missing_keys,
                duplicate_keys=self.duplicate_keys,
                uncited_keys=self.uncited_keys,
            ),
        )

    def _validate_group_occurrences(self) -> None:
        flattened = tuple(
            index for group in self.groups for index in group.occurrence_indexes
        )
        if tuple(sorted(flattened)) != tuple(range(len(self.occurrences))):
            raise ValueError(
                "citation groups do not partition target occurrences"
            )
        for group in self.groups:
            occurrences = tuple(
                self.occurrences[index] for index in group.occurrence_indexes
            )
            if any(item.key != group.key for item in occurrences):
                raise ValueError("citation group contains another literal key")
            direct = sum(item.origin == "direct" for item in occurrences)
            generated = len(occurrences) - direct
            if (
                direct != group.direct_occurrence_count
                or generated != group.generated_occurrence_count
                or any(
                    item.bibliography_entry_index
                    != group.bibliography_entry_index
                    for item in occurrences
                )
            ):
                raise ValueError("citation group occurrence evidence conflicts")

    def _validate_bibliography(self) -> None:
        for entry in self.bibliography_entries:
            if (
                entry.locator.source_path != self.bibliography_source_path
                or entry.locator.source_content_identity
                != self.bibliography_content_identity
            ):
                raise ValueError(
                    "bibliography entry conflicts with source identity"
                )
        entries_by_key: dict[str, list[CitationTargetBibliographyEntry]] = {}
        for entry in self.bibliography_entries:
            entries_by_key.setdefault(entry.key, []).append(entry)
        for group in self.groups:
            entries = entries_by_key.get(group.key, [])
            expected = entries[0].entry_index if len(entries) == 1 else None
            if group.bibliography_entry_index != expected:
                raise ValueError(
                    "citation group bibliography binding is not fail-closed"
                )

    def _validate_key_sets(self) -> None:
        for values, field_name in (
            (self.missing_keys, "missing_keys"),
            (self.duplicate_keys, "duplicate_keys"),
            (self.uncited_keys, "uncited_keys"),
        ):
            if (
                not isinstance(values, tuple)
                or values != tuple(sorted(set(values)))
                or any(not isinstance(item, str) for item in values)
            ):
                raise ValueError(f"{field_name} must be sorted and unique")
            for key in values:
                validate_citekey(key, field=field_name)
        group_keys = {item.key for item in self.groups}
        counts: dict[str, int] = {}
        for entry in self.bibliography_entries:
            counts[entry.key] = counts.get(entry.key, 0) + 1
        if (
            self.missing_keys != tuple(sorted(group_keys - set(counts)))
            or self.duplicate_keys
            != tuple(sorted(key for key, count in counts.items() if count > 1))
            or self.uncited_keys != tuple(sorted(set(counts) - group_keys))
        ):
            raise ValueError("target bibliography key sets conflict")

    def _validate_external_ids(self) -> None:
        identity_groups = (
            tuple(item.occurrence_id for item in self.occurrences),
            tuple(item.group_id for item in self.groups),
            tuple(item.entry_id for item in self.bibliography_entries),
            tuple(item.source_gap_id for item in self.source_gaps),
        )
        for values in identity_groups:
            if len(values) != len(set(values)):
                raise ValueError(
                    "target snapshot identities contain duplicates"
                )

    def validate_identity(self) -> None:
        _CitationDocumentContract.validate_identity(
            actual=self.target_projection_id,
            prefix="citation-target-projection",
            payload={
                "snapshot_id": self.snapshot_id,
                "bibliography_source_path": self.bibliography_source_path,
                "bibliography_content_identity": (
                    self.bibliography_content_identity
                ),
                "occurrences": self.occurrences,
                "groups": self.groups,
                "bibliography_entries": self.bibliography_entries,
                "source_gaps": self.source_gaps,
                "missing_keys": self.missing_keys,
                "duplicate_keys": self.duplicate_keys,
                "uncited_keys": self.uncited_keys,
            },
            field_name="target citation projection identity",
        )

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _CitationDocumentContract.stable_id(
            "citation-target-projection",
            payload,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationBibliographyObservationBinding(DataObjectModel):
    """Exact target-entry binding to one References source observation."""

    entry: CitationTargetBibliographyEntry
    observation: SourceBibliographyObservation
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.entry, CitationTargetBibliographyEntry):
            raise TypeError("entry must be a CitationTargetBibliographyEntry")
        if not isinstance(self.observation, SourceBibliographyObservation):
            raise TypeError(
                "observation must be a SourceBibliographyObservation"
            )
        if (
            self.observation.observed_citekey != self.entry.key
            or self.observation.entry_index != self.entry.entry_index
            or self.observation.source_path != self.entry.locator.source_path
            or self.observation.bibliography_sha256
            != self.entry.locator.source_content_identity.digest
            or self.observation.bibliography_byte_size
            != self.entry.locator.source_content_identity.byte_count
        ):
            raise ValueError(
                "bibliography observation conflicts with target entry"
            )
        verbatim = self.observation.verbatim_entry.encode("utf-8")
        if (
            hashlib.sha256(verbatim).hexdigest()
            != self.entry.entry_content_identity.digest
            or len(verbatim) != self.entry.entry_content_identity.byte_count
        ):
            raise ValueError(
                "bibliography observation verbatim entry conflicts"
            )
        if (
            self.entry.source_bibliography_observation_id is not None
            and self.entry.source_bibliography_observation_id
            != self.observation.observation_id
        ):
            raise ValueError(
                "target bibliography observation identity conflicts"
            )
        object.__setattr__(
            self,
            "binding_id",
            _CitationDocumentContract.stable_id(
                "citation-bibliography-binding",
                {
                    "entry_id": self.entry.entry_id,
                    "observation_id": self.observation.observation_id,
                },
            ),
        )


class CitationKeyResolutionStatus(StrEnum):
    """Literal-key correlation without first-match selection."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class CitationBibliographyMembershipStatus(StrEnum):
    """Target bibliography membership, separate from identity resolution."""

    DEFINED = "defined"
    UNDEFINED = "undefined"
    NOT_EVALUATED = "not-evaluated"


class CitationDocumentAvailabilityStatus(StrEnum):
    """Document evidence separate from rights, use, and ingestion."""

    NOT_EVALUATED = "not-evaluated"
    NOT_OBSERVED = "not-observed"
    AVAILABLE_UNVERIFIED_LINKAGE = "available-unverified-linkage"
    AVAILABLE_LINKED = "available-linked"
    AMBIGUOUS = "ambiguous"
    INACCESSIBLE = "inaccessible"


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentDescriptor(DataObjectModel):
    """Opaque PDF descriptor without bytes, path, rights, or ingestion state."""

    source_document_id: str
    sha256: str
    byte_size: int
    media_type: str = "application/pdf"
    descriptor_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.opaque_id(
            self.source_document_id,
            field_name="source document identity",
        )
        if not _CitationDocumentContract._DIGEST.fullmatch(self.sha256):
            raise ValueError("source document SHA-256 is invalid")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("source document byte size is invalid")
        if self.media_type != "application/pdf":
            raise ValueError(
                "source document media type must be application/pdf"
            )
        object.__setattr__(
            self,
            "descriptor_id",
            _CitationDocumentContract.stable_id(
                "citation-source-document-descriptor",
                {
                    "source_document_id": self.source_document_id,
                    "sha256": self.sha256,
                    "byte_size": self.byte_size,
                    "media_type": self.media_type,
                },
            ),
        )

    @property
    def content_key(self) -> tuple[str, int]:
        return (self.sha256, self.byte_size)


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationSourceDocumentObservation(DataObjectModel):
    """Bounded document availability evidence for one literal key."""

    target_snapshot_id: str
    literal_citekey: str
    coverage_status: str
    source_documents: tuple[CitationSourceDocumentDescriptor, ...]
    inaccessible_evidence_ids: tuple[str, ...]
    evidence_id: str
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        _CitationDocumentContract.target_id(
            self.target_snapshot_id,
            kind="snapshot",
            field_name="document observation target snapshot",
        )
        validate_citekey(self.literal_citekey, field="document observation key")
        if self.coverage_status not in {"complete", "incomplete"}:
            raise ValueError("document evidence coverage status is invalid")
        if (
            not isinstance(self.source_documents, tuple)
            or len(self.source_documents)
            > CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY
            or any(
                not isinstance(item, CitationSourceDocumentDescriptor)
                for item in self.source_documents
            )
        ):
            raise TypeError("source document descriptors are invalid")
        descriptor_ids = tuple(
            item.descriptor_id for item in self.source_documents
        )
        if descriptor_ids != tuple(sorted(descriptor_ids)) or len(
            descriptor_ids
        ) != len(set(descriptor_ids)):
            raise ValueError("source document descriptors are not canonical")
        source_ids = tuple(
            item.source_document_id for item in self.source_documents
        )
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source document identities contain duplicates")
        if not isinstance(
            self.inaccessible_evidence_ids, tuple
        ) or self.inaccessible_evidence_ids != tuple(
            sorted(set(self.inaccessible_evidence_ids))
        ):
            raise ValueError(
                "inaccessible evidence identities are not canonical"
            )
        for identity in self.inaccessible_evidence_ids:
            _CitationDocumentContract.opaque_id(
                identity,
                field_name="inaccessible evidence identity",
            )
        _CitationDocumentContract.opaque_id(
            self.evidence_id,
            field_name="document observation evidence identity",
        )
        object.__setattr__(
            self,
            "observation_id",
            _CitationDocumentContract.stable_id(
                "citation-source-document-observation",
                {
                    "target_snapshot_id": self.target_snapshot_id,
                    "literal_citekey": self.literal_citekey,
                    "coverage_status": self.coverage_status,
                    "source_documents": self.source_documents,
                    "inaccessible_evidence_ids": (
                        self.inaccessible_evidence_ids
                    ),
                    "evidence_id": self.evidence_id,
                },
            ),
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
            _CitationDocumentContract.opaque_id(
                value,
                field_name=field_name,
            )
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
        _CitationDocumentContract.validate_identity(
            actual=self.link_id,
            prefix="citation-source-document-link",
            payload=self.identity_payload(),
            field_name="citation source-document link identity",
        )

    @staticmethod
    def expected_limitations() -> tuple[str, ...]:
        return (
            "not-canonical-asset-authorization",
            "not-ingestion-status",
            "not-manuscript-use-authorization",
            "not-publication-authorization",
            "not-review-decision",
            "not-rights-clearance",
            "not-scientific-support",
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
            "source_document": self.source_document,
            "availability_observation_ids": (self.availability_observation_ids),
            "pre_effect_intent_id": self.pre_effect_intent_id,
            "linkage_basis": self.linkage_basis,
            "limitations": self.limitations,
        }

    def validate_identity(self) -> None:
        _CitationDocumentContract.validate_identity(
            actual=self.link_id,
            prefix="citation-source-document-link",
            payload=self.identity_payload(),
            field_name="citation source-document link identity",
        )


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
        validate_citekey(self.literal_citekey, field="projection literal key")
        if (
            not isinstance(self.occurrence_ids, tuple)
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
        if not isinstance(
            self.bibliography_membership_status,
            CitationBibliographyMembershipStatus,
        ):
            raise TypeError("bibliography membership status is invalid")
        if not isinstance(
            self.key_resolution_status,
            CitationKeyResolutionStatus,
        ):
            raise TypeError("key resolution status is invalid")
        if not isinstance(self.identity_items, tuple) or any(
            not isinstance(item, CitationIdentityProjectionItem)
            for item in self.identity_items
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
        if not isinstance(
            self.document_status,
            CitationDocumentAvailabilityStatus,
        ):
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
                CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
            ),
        ):
            if (
                not isinstance(values, tuple)
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
            _CitationDocumentContract.stable_id(
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
            "occurrence_ids": self.occurrence_ids,
            "bibliography_membership_status": (
                self.bibliography_membership_status
            ),
            "key_resolution_status": self.key_resolution_status,
            "identity_item_ids": tuple(
                item.item_id for item in self.identity_items
            ),
            "document_status": self.document_status,
            "source_document_ids": self.source_document_ids,
            "source_document_link_ids": self.source_document_link_ids,
        }


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
        if self.contract_id != CITATION_DOCUMENT_PROJECTION_CONTRACT_ID:
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
                not isinstance(values, tuple)
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
            not isinstance(self.source_documents, tuple)
            or len(self.source_documents)
            > CITATION_DOCUMENT_MAX_SOURCE_DOCUMENTS
            or any(
                not isinstance(item, CitationSourceDocumentDescriptor)
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
            not isinstance(self.items, tuple)
            or len(self.items) > CITATION_DOCUMENT_MAX_KEYS
            or any(
                not isinstance(item, CitationDocumentProjectionItem)
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
            not isinstance(self.source_gaps, tuple)
            or len(self.source_gaps) > CITATION_DOCUMENT_MAX_SOURCE_GAPS
            or any(
                not isinstance(item, CitationTargetSourceGap)
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
        if self.limitations != self.expected_limitations():
            raise ValueError("citation document limitations are invalid")
        self.validate_identity()

    @staticmethod
    def expected_limitations() -> tuple[str, ...]:
        return (
            "not-ingestion-status",
            "not-manuscript-use-authorization",
            "not-publication-authorization",
            "not-review-decision",
            "not-rights-clearance",
            "not-scientific-support",
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "target_snapshot_id": self.target_snapshot_id,
            "target_projection_id": self.target_projection_id,
            "bibliography_binding_ids": self.bibliography_binding_ids,
            "identity_projection_id": self.identity_projection_id,
            "document_observation_ids": self.document_observation_ids,
            "source_document_link_ids": self.source_document_link_ids,
            "source_document_descriptor_ids": tuple(
                item.descriptor_id for item in self.source_documents
            ),
            "item_ids": tuple(item.item_id for item in self.items),
            "source_gap_ids": tuple(
                item.source_gap_id for item in self.source_gaps
            ),
            "limitations": self.limitations,
        }

    def validate_identity(self) -> None:
        _CitationDocumentContract.validate_identity(
            actual=self.projection_id,
            prefix="citation-document-projection",
            payload=self.identity_payload(),
            field_name="citation document projection identity",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentProjectionRequest(DataObjectActionRequest):
    """Complete immutable inputs to one citation/document projection."""

    target_snapshot: CitationTargetSnapshot
    bibliography_bindings: tuple[CitationBibliographyObservationBinding, ...]
    identity_projection: IdentityProjection
    document_observations: tuple[CitationSourceDocumentObservation, ...] = ()
    source_document_links: tuple[CitationSourceDocumentLink, ...] = ()
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.target_snapshot) is not CitationTargetSnapshot:
            raise TypeError("target_snapshot must be a CitationTargetSnapshot")
        self.target_snapshot.validate_identity()
        if (
            not isinstance(self.bibliography_bindings, tuple)
            or len(self.bibliography_bindings)
            != len(self.target_snapshot.bibliography_entries)
            or any(
                not isinstance(
                    item,
                    CitationBibliographyObservationBinding,
                )
                for item in self.bibliography_bindings
            )
        ):
            raise TypeError("bibliography bindings are invalid")
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
            not isinstance(self.document_observations, tuple)
            or len(self.document_observations) > CITATION_DOCUMENT_MAX_KEYS
            or any(
                not isinstance(item, CitationSourceDocumentObservation)
                for item in self.document_observations
            )
        ):
            raise TypeError("document observations are invalid")
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
        if (
            not isinstance(self.source_document_links, tuple)
            or len(self.source_document_links) > CITATION_DOCUMENT_MAX_LINKS
            or any(
                not isinstance(item, CitationSourceDocumentLink)
                for item in self.source_document_links
            )
        ):
            raise TypeError("source document links are invalid")
        link_ids = tuple(item.link_id for item in self.source_document_links)
        if link_ids != tuple(sorted(set(link_ids))):
            raise ValueError("source document links are not canonical")
        for link in self.source_document_links:
            link.validate_identity()
        object.__setattr__(
            self,
            "request_id",
            _CitationDocumentContract.stable_id(
                "citation-document-projection-request",
                {
                    "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
                    "target_projection_id": (
                        self.target_snapshot.target_projection_id
                    ),
                    "bibliography_binding_ids": tuple(sorted(binding_ids)),
                    "identity_projection_id": (
                        self.identity_projection.projection_id
                    ),
                    "document_observation_ids": tuple(
                        item.observation_id
                        for item in self.document_observations
                    ),
                    "source_document_link_ids": link_ids,
                },
            ),
        )


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
        if (
            self.projection.target_snapshot_id
            != self.request.target_snapshot.snapshot_id
            or self.projection.identity_projection_id
            != self.request.identity_projection.projection_id
        ):
            raise ValueError("projection result source identity conflicts")
        object.__setattr__(
            self,
            "result_id",
            _CitationDocumentContract.stable_id(
                "citation-document-projection-result",
                {
                    "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
                    "projector": CITATION_DOCUMENT_PROJECTOR_NAME,
                    "request_id": self.request.request_id,
                    "projection_id": self.projection.projection_id,
                },
            ),
        )

    def validate_identity(self) -> None:
        self.projection.validate_identity()
        _CitationDocumentContract.validate_identity(
            actual=self.result_id,
            prefix="citation-document-projection-result",
            payload={
                "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
                "projector": CITATION_DOCUMENT_PROJECTOR_NAME,
                "request_id": self.request.request_id,
                "projection_id": self.projection.projection_id,
            },
            field_name="citation document projection result identity",
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
            _CitationDocumentContract.stable_id(
                "citation-source-document-link-request",
                {
                    "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
                    "projection_result_id": self.projection_result.result_id,
                    "item_id": self.item_id,
                    "identity_item_id": self.identity_item_id,
                    "source_document_id": self.source_document_id,
                    "pre_effect_intent_id": self.pre_effect_intent_id,
                    "linkage_basis": self.linkage_basis,
                },
            ),
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
        if self.link.creating_request_id != self.request.request_id:
            raise ValueError("link result request identity conflicts")
        self.link.validate_identity()
        object.__setattr__(
            self,
            "result_id",
            _CitationDocumentContract.stable_id(
                "citation-source-document-link-result",
                {
                    "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
                    "linker": CITATION_SOURCE_DOCUMENT_LINKER_NAME,
                    "request_id": self.request.request_id,
                    "link_id": self.link.link_id,
                },
            ),
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
            and any(
                candidate == descriptor for candidate in value.source_documents
            )
        )
        if not observations:
            raise ValueError("source document has no availability observation")
        payload = {
            "contract_id": CITATION_SOURCE_DOCUMENT_LINK_CONTRACT_ID,
            "creating_request_id": request.request_id,
            "prior_projection_id": projection.projection_id,
            "prior_item_id": item.item_id,
            "target_snapshot_id": projection.target_snapshot_id,
            "identity_projection_id": projection.identity_projection_id,
            "literal_citekey": item.literal_citekey,
            "identity_item_id": identity_item.item_id,
            "requested_identity_id": identity_item.requested_identity_id,
            "source_document": descriptor,
            "availability_observation_ids": tuple(sorted(observations)),
            "pre_effect_intent_id": request.pre_effect_intent_id,
            "linkage_basis": request.linkage_basis,
            "limitations": CitationSourceDocumentLink.expected_limitations(),
        }
        link = CitationSourceDocumentLink(
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
            link_id=_CitationDocumentContract.stable_id(
                "citation-source-document-link",
                payload,
            ),
        )
        return CitationSourceDocumentLinkResult(request=request, link=link)


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
        return self.project(request=request)

    def project(
        self,
        *,
        request: CitationDocumentProjectionRequest,
    ) -> CitationDocumentProjectionResult:
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
        links_by_key = self._links_by_key(request.source_document_links)
        items: list[CitationDocumentProjectionItem] = []
        for group in request.target_snapshot.groups:
            ids = identity_ids_by_key[group.key]
            projected = tuple(item_by_identity[item] for item in ids)
            key_status = self._key_status(projected)
            observations = observations_by_key.get(group.key, ())
            links = links_by_key.get(group.key, ())
            self._validate_links(
                request=request,
                group=group,
                identity_items=projected,
                observations=observations,
                links=links,
                source_by_id=source_by_id,
            )
            document_status = self._document_status(
                key_status=key_status,
                observations=observations,
                links=links,
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
                        sorted(item.link_id for item in links)
                    ),
                )
            )
        projection_payload = {
            "contract_id": CITATION_DOCUMENT_PROJECTION_CONTRACT_ID,
            "target_snapshot_id": request.target_snapshot.snapshot_id,
            "target_projection_id": (
                request.target_snapshot.target_projection_id
            ),
            "bibliography_binding_ids": tuple(
                sorted(
                    item.binding_id for item in request.bibliography_bindings
                )
            ),
            "identity_projection_id": request.identity_projection.projection_id,
            "document_observation_ids": tuple(
                sorted(
                    item.observation_id
                    for item in request.document_observations
                )
            ),
            "source_document_link_ids": tuple(
                item.link_id for item in request.source_document_links
            ),
            "source_document_descriptor_ids": tuple(
                item.descriptor_id for item in source_documents
            ),
            "item_ids": tuple(item.item_id for item in items),
            "source_gap_ids": tuple(
                item.source_gap_id
                for item in request.target_snapshot.source_gaps
            ),
            "limitations": CitationDocumentProjection.expected_limitations(),
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
            source_document_link_ids=tuple(
                item.link_id for item in request.source_document_links
            ),
            source_documents=source_documents,
            items=tuple(items),
            source_gaps=request.target_snapshot.source_gaps,
            limitations=CitationDocumentProjection.expected_limitations(),
            projection_id=_CitationDocumentContract.stable_id(
                "citation-document-projection",
                projection_payload,
            ),
        )
        return CitationDocumentProjectionResult(
            request=request,
            projection=projection,
        )

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
