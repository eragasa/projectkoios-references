from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

from projectkoios.base import DataObjectModel
from projectkoios.references.identity import SourceBibliographyObservation

from ._contract import (
    CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES,
    CITATION_DOCUMENT_MAX_ID_BYTES,
    CITATION_DOCUMENT_MAX_KEYS,
    CITATION_DOCUMENT_MAX_OCCURRENCES,
    CITATION_DOCUMENT_MAX_SOURCE_GAPS,
    CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_RECORDS,
    CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD,
    CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES,
    _CitationDocumentContract,
    stable_id,
    validate_literal_citekey,
    validate_source_path,
)


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
        if (
            type(self.byte_count) is not int
            or not 0
            < self.byte_count
            <= CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES
        ):
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
        validate_source_path(
            self.source_path,
            field_name="citation source path",
        )
        if not isinstance(
            self.source_content_identity,
            CitationContentIdentity,
        ):
            raise TypeError(
                "source_content_identity must be a CitationContentIdentity"
            )
        if (
            type(self.include_index) is not int
            or self.include_index < 0
            or self.include_index >= CITATION_DOCUMENT_MAX_OCCURRENCES
        ):
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
        for value, field_name, maximum in (
            (
                self.occurrence_index,
                "occurrence_index",
                CITATION_DOCUMENT_MAX_OCCURRENCES,
            ),
            (
                self.call_index,
                "call_index",
                CITATION_DOCUMENT_MAX_OCCURRENCES,
            ),
            (
                self.key_index,
                "key_index",
                CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD,
            ),
        ):
            if type(value) is not int or not 0 <= value < maximum:
                raise ValueError(f"{field_name} is outside the canonical bound")
        validate_literal_citekey(
            self.key,
            field_name="literal citation key",
        )
        if self.origin not in {
            "direct",
            "eqincite_expansion",
            "citation_todo_expansion",
        }:
            raise ValueError("citation occurrence origin is invalid")
        if not isinstance(self.locator, CitationSourceLocator):
            raise TypeError("locator must be a CitationSourceLocator")
        if self.bibliography_entry_index is not None and (
            type(self.bibliography_entry_index) is not int
            or not 0
            <= self.bibliography_entry_index
            < CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES
        ):
            raise ValueError("bibliography entry index is invalid")
        if self.origin == "citation_todo_expansion":
            if (
                type(self.todo_marker_index) is not int
                or not 0
                <= self.todo_marker_index
                < CITATION_DOCUMENT_MAX_OCCURRENCES
            ):
                raise ValueError(
                    "generated citation requires a todo marker index"
                )
        elif self.todo_marker_index is not None:
            raise ValueError(
                "non-todo citation cannot bind a todo marker index"
            )


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
        if (
            type(self.group_index) is not int
            or not 0 <= self.group_index < CITATION_DOCUMENT_MAX_KEYS
        ):
            raise ValueError("citation group index is invalid")
        validate_literal_citekey(
            self.key,
            field_name="citation group key",
        )
        if (
            not isinstance(self.occurrence_indexes, tuple)
            or not self.occurrence_indexes
            or len(self.occurrence_indexes)
            > CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD
            or any(
                type(item) is not int
                or not 0 <= item < CITATION_DOCUMENT_MAX_OCCURRENCES
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
            if (
                type(value) is not int
                or not 0
                <= value
                <= CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD
            ):
                raise ValueError(f"{field_name} is invalid")
        if self.direct_occurrence_count + self.generated_occurrence_count != (
            len(self.occurrence_indexes)
        ):
            raise ValueError("citation group counts conflict")
        if self.bibliography_entry_index is not None and (
            type(self.bibliography_entry_index) is not int
            or not 0
            <= self.bibliography_entry_index
            < CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES
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
        if (
            type(self.entry_index) is not int
            or not 0
            <= self.entry_index
            < CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES
        ):
            raise ValueError("citation bibliography entry index is invalid")
        validate_literal_citekey(
            self.key,
            field_name="bibliography entry key",
        )
        _CitationDocumentContract.bounded_text(
            self.entry_type,
            field_name="bibliography entry type",
            maximum=CITATION_DOCUMENT_MAX_ID_BYTES,
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
        if (
            type(self.source_gap_index) is not int
            or not 0
            <= self.source_gap_index
            < CITATION_DOCUMENT_MAX_SOURCE_GAPS
        ):
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


def _content_identity_value(
    value: CitationContentIdentity,
) -> dict[str, object]:
    return {
        "algorithm": value.algorithm,
        "digest": value.digest,
        "byte_count": value.byte_count,
    }


def _locator_value(value: CitationSourceLocator) -> dict[str, object]:
    return {
        "source_path": value.source_path,
        "source_content_identity": _content_identity_value(
            value.source_content_identity
        ),
        "include_index": value.include_index,
        "byte_start": value.byte_start,
        "byte_end": value.byte_end,
        "line": value.line,
        "column": value.column,
    }


def _occurrence_value(
    value: CitationTargetOccurrence,
) -> dict[str, object]:
    return {
        "occurrence_id": value.occurrence_id,
        "occurrence_index": value.occurrence_index,
        "call_index": value.call_index,
        "key_index": value.key_index,
        "key": value.key,
        "origin": value.origin,
        "locator": _locator_value(value.locator),
        "bibliography_entry_index": value.bibliography_entry_index,
        "todo_marker_index": value.todo_marker_index,
    }


def _group_value(value: CitationTargetGroup) -> dict[str, object]:
    return {
        "group_id": value.group_id,
        "group_index": value.group_index,
        "key": value.key,
        "occurrence_indexes": list(value.occurrence_indexes),
        "direct_occurrence_count": value.direct_occurrence_count,
        "generated_occurrence_count": value.generated_occurrence_count,
        "bibliography_entry_index": value.bibliography_entry_index,
    }


def _bibliography_entry_value(
    value: CitationTargetBibliographyEntry,
) -> dict[str, object]:
    return {
        "entry_id": value.entry_id,
        "entry_index": value.entry_index,
        "key": value.key,
        "entry_type": value.entry_type,
        "locator": _locator_value(value.locator),
        "entry_content_identity": _content_identity_value(
            value.entry_content_identity
        ),
        "source_bibliography_observation_id": (
            value.source_bibliography_observation_id
        ),
    }


def _source_gap_value(
    value: CitationTargetSourceGap,
) -> dict[str, object]:
    return {
        "source_gap_id": value.source_gap_id,
        "source_gap_index": value.source_gap_index,
        "locator": _locator_value(value.locator),
        "reason": value.reason,
        "placeholder_identifier": value.placeholder_identifier,
    }


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
        validate_source_path(
            self.bibliography_source_path,
            field_name="bibliography source path",
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
        if sum(len(values) for values, _, _, _ in typed_values) > (
            CITATION_DOCUMENT_MAX_TARGET_RECORDS
        ):
            raise ValueError("target aggregate record count exceeds the limit")
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
        self._validate_source_content()
        self._validate_bibliography()
        self._validate_key_sets()
        self._validate_external_ids()
        object.__setattr__(
            self,
            "target_projection_id",
            stable_id(
                "citation-target-projection",
                self._identity_payload(),
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
            generated = sum(
                item.origin == "citation_todo_expansion" for item in occurrences
            )
            direct = len(occurrences) - generated
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

    def _validate_source_content(self) -> None:
        by_path: dict[str, CitationContentIdentity] = {
            self.bibliography_source_path: self.bibliography_content_identity
        }
        locators = (
            *(item.locator for item in self.occurrences),
            *(item.locator for item in self.source_gaps),
        )
        for locator in locators:
            existing = by_path.get(locator.source_path)
            if (
                existing is not None
                and existing != locator.source_content_identity
            ):
                raise ValueError(
                    "target source path has conflicting content identities"
                )
            by_path[locator.source_path] = locator.source_content_identity
        if len(by_path) > CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES + 1:
            raise ValueError("target source identity count exceeds the limit")
        if sum(item.byte_count for item in by_path.values()) > (
            CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES
        ):
            raise ValueError("target aggregate source bytes exceed the limit")

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
                validate_literal_citekey(key, field_name=field_name)
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

    def _identity_payload(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "bibliography_source_path": self.bibliography_source_path,
            "bibliography_content_identity": _content_identity_value(
                self.bibliography_content_identity
            ),
            "occurrences": [
                _occurrence_value(item) for item in self.occurrences
            ],
            "groups": [_group_value(item) for item in self.groups],
            "bibliography_entries": [
                _bibliography_entry_value(item)
                for item in self.bibliography_entries
            ],
            "source_gaps": [
                _source_gap_value(item) for item in self.source_gaps
            ],
            "missing_keys": list(self.missing_keys),
            "duplicate_keys": list(self.duplicate_keys),
            "uncited_keys": list(self.uncited_keys),
        }

    def validate_identity(self) -> None:
        rebuilt = replace(self)
        if rebuilt != self:
            raise ValueError("target citation projection does not match replay")
        _CitationDocumentContract.validate_identity(
            actual=self.target_projection_id,
            prefix="citation-target-projection",
            payload=self._identity_payload(),
            field_name="target citation projection identity",
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
            stable_id(
                "citation-bibliography-binding",
                {
                    "entry_id": self.entry.entry_id,
                    "observation_id": self.observation.observation_id,
                },
            ),
        )

    def validate_identity(self) -> None:
        if replace(self.observation) != self.observation:
            raise ValueError(
                "source bibliography observation does not match replay"
            )
        rebuilt = replace(self)
        if rebuilt != self:
            raise ValueError("bibliography binding does not match replay")
