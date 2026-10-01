from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from projectkoios.references.citation_document import (
    CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES,
    CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS,
    CITATION_DOCUMENT_MAX_ID_BYTES,
    CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_RECORDS,
    CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD,
    CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES,
    CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES,
    CITATION_DOCUMENT_MAX_TEXT_BYTES,
    CitationContentIdentity,
    CitationSourceLocator,
    CitationTargetBibliographyEntry,
    CitationTargetGroup,
    CitationTargetOccurrence,
    CitationTargetSnapshot,
    CitationTargetSourceGap,
)
from projectkoios.references.path_safety import (
    PathSafetyError,
    validate_citekey,
    validate_relative_path,
)

REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = (
    REPOSITORY
    / "tests"
    / "fixtures"
    / "citation_document"
    / "ksdft-3ec21b4-compact-result.json"
)
OWNER_COMMIT = "3ec21b4318020d700be671a8f220b2149b3d28c7"
OWNER_TREE = "9953c0e99a28443426b5093852292f7cfbada2cc"
FIXTURE_SHA256 = (
    "d0019af4bcd5d3331c5ffc499bb95838215f09cc7d54b61d45b72456ed3db70d"
)
OWNER_REQUEST_ID = (
    "citation-request:"
    "e87223c3350eb97c3a28b377d28bd46cf96bd599d3c5b01149af6e62fc34602d"
)
OWNER_RESULT_ID = (
    "citation-result:"
    "7888050dbd54e0e96726819fe8b49f261e96cb9c856ae3f5259df28af77f0b9f"
)
OWNER_SNAPSHOT_ID = (
    "citation-snapshot:"
    "0a80a52f4f6e66a76b2a76d2c849114f97e8306f418b6de17b6013b8bc26834d"
)
REFERENCES_TARGET_PROJECTION_ID = (
    "citation-target-projection:sha256:"
    "ae64a0f4acaa995b0b81f4c85ed3037bdde9ea3bc1aa2007b6af27a43636e299"
)


def _object(value: object) -> dict[str, object]:
    assert type(value) is dict
    return cast(dict[str, object], value)


def _objects(value: object) -> tuple[dict[str, object], ...]:
    assert type(value) is list
    return tuple(_object(item) for item in cast(list[object], value))


def _strings(value: object) -> tuple[str, ...]:
    assert type(value) is list
    values = cast(list[object], value)
    assert all(type(item) is str for item in values)
    return tuple(cast(str, item) for item in values)


def _integers(value: object) -> tuple[int, ...]:
    assert type(value) is list
    values = cast(list[object], value)
    assert all(type(item) is int for item in values)
    return tuple(cast(int, item) for item in values)


def _text(value: object) -> str:
    assert type(value) is str
    return value


def _integer(value: object) -> int:
    assert type(value) is int
    return value


def _optional_integer(value: object) -> int | None:
    assert value is None or type(value) is int
    return cast(int | None, value)


def _optional_text(value: object) -> str | None:
    assert value is None or type(value) is str
    return cast(str | None, value)


def _content(value: object) -> CitationContentIdentity:
    data = _object(value)
    assert set(data) == {"algorithm", "byte_count", "digest"}
    return CitationContentIdentity(
        algorithm=_text(data["algorithm"]),
        digest=_text(data["digest"]),
        byte_count=_integer(data["byte_count"]),
    )


def _locator(value: object) -> CitationSourceLocator:
    data = _object(value)
    assert set(data) == {
        "byte_end",
        "byte_start",
        "column",
        "include_index",
        "line",
        "source_content_identity",
        "source_path",
    }
    return CitationSourceLocator(
        source_path=_text(data["source_path"]),
        source_content_identity=_content(data["source_content_identity"]),
        include_index=_integer(data["include_index"]),
        byte_start=_integer(data["byte_start"]),
        byte_end=_integer(data["byte_end"]),
        line=_integer(data["line"]),
        column=_integer(data["column"]),
    )


def _adapt_snapshot(value: object) -> CitationTargetSnapshot:
    data = _object(value)
    assert set(data) == {
        "bibliography_content_identity",
        "bibliography_entries",
        "bibliography_path",
        "calls",
        "contract_id",
        "duplicate_keys",
        "entrypoint_path",
        "generator_identity",
        "groups",
        "include_instances",
        "missing_keys",
        "occurrences",
        "parser_identity",
        "repository_revision",
        "snapshot_id",
        "source_files",
        "source_gaps",
        "todos",
        "uncited_keys",
    }
    occurrence_values = _objects(data["occurrences"])
    assert all(
        set(item)
        == {
            "bibliography_entry_index",
            "call_index",
            "key",
            "key_index",
            "locator",
            "occurrence_id",
            "occurrence_index",
            "origin",
            "todo_marker_index",
        }
        for item in occurrence_values
    )
    group_values = _objects(data["groups"])
    assert all(
        set(item)
        == {
            "bibliography_entry_index",
            "direct_occurrence_count",
            "generated_occurrence_count",
            "group_id",
            "group_index",
            "key",
            "occurrence_indexes",
        }
        for item in group_values
    )
    entry_values = _objects(data["bibliography_entries"])
    assert all(
        set(item)
        == {
            "bibliography_entry_id",
            "entry_content_identity",
            "entry_index",
            "entry_type",
            "key",
            "locator",
            "source_bibliography_observation_id",
        }
        for item in entry_values
    )
    gap_values = _objects(data["source_gaps"])
    assert all(
        set(item)
        == {
            "locator",
            "placeholder_identifier",
            "reason",
            "source_gap_id",
            "source_gap_index",
        }
        for item in gap_values
    )
    occurrences = tuple(
        CitationTargetOccurrence(
            occurrence_id=_text(item["occurrence_id"]),
            occurrence_index=_integer(item["occurrence_index"]),
            call_index=_integer(item["call_index"]),
            key_index=_integer(item["key_index"]),
            key=_text(item["key"]),
            origin=_text(item["origin"]),
            locator=_locator(item["locator"]),
            bibliography_entry_index=_optional_integer(
                item["bibliography_entry_index"]
            ),
            todo_marker_index=_optional_integer(item["todo_marker_index"]),
        )
        for item in occurrence_values
    )
    groups = tuple(
        CitationTargetGroup(
            group_id=_text(item["group_id"]),
            group_index=_integer(item["group_index"]),
            key=_text(item["key"]),
            occurrence_indexes=_integers(item["occurrence_indexes"]),
            direct_occurrence_count=_integer(item["direct_occurrence_count"]),
            generated_occurrence_count=_integer(
                item["generated_occurrence_count"]
            ),
            bibliography_entry_index=_optional_integer(
                item["bibliography_entry_index"]
            ),
        )
        for item in group_values
    )
    entries = tuple(
        CitationTargetBibliographyEntry(
            entry_id=_text(item["bibliography_entry_id"]),
            entry_index=_integer(item["entry_index"]),
            key=_text(item["key"]),
            entry_type=_text(item["entry_type"]),
            locator=_locator(item["locator"]),
            entry_content_identity=_content(item["entry_content_identity"]),
            source_bibliography_observation_id=_optional_text(
                item["source_bibliography_observation_id"]
            ),
        )
        for item in entry_values
    )
    gaps = tuple(
        CitationTargetSourceGap(
            source_gap_id=_text(item["source_gap_id"]),
            source_gap_index=_integer(item["source_gap_index"]),
            locator=_locator(item["locator"]),
            reason=_text(item["reason"]),
            placeholder_identifier=_text(item["placeholder_identifier"]),
        )
        for item in gap_values
    )
    return CitationTargetSnapshot(
        snapshot_id=_text(data["snapshot_id"]),
        bibliography_source_path=_text(data["bibliography_path"]),
        bibliography_content_identity=_content(
            data["bibliography_content_identity"]
        ),
        occurrences=occurrences,
        groups=groups,
        bibliography_entries=entries,
        source_gaps=gaps,
        missing_keys=_strings(data["missing_keys"]),
        duplicate_keys=_strings(data["duplicate_keys"]),
        uncited_keys=_strings(data["uncited_keys"]),
    )


def test__corrected_ksdft_result__adapts_exact_neutral_shape() -> None:
    fixture_bytes = FIXTURE.read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == FIXTURE_SHA256
    payload = _object(json.loads(fixture_bytes))
    assert set(payload) == {"request_id", "result_id", "snapshot"}
    assert _text(payload["request_id"]) == OWNER_REQUEST_ID
    assert _text(payload["result_id"]) == OWNER_RESULT_ID

    owner_snapshot = _object(payload["snapshot"])
    snapshot = _adapt_snapshot(owner_snapshot)

    assert snapshot.snapshot_id == OWNER_SNAPSHOT_ID
    assert snapshot.target_projection_id == REFERENCES_TARGET_PROJECTION_ID
    assert len(snapshot.occurrences) == 5
    assert len(snapshot.groups) == 2
    assert len(snapshot.bibliography_entries) == 2
    assert len(snapshot.source_gaps) == 1
    assert tuple(item.origin for item in snapshot.occurrences) == (
        "direct",
        "direct",
        "eqincite_expansion",
        "citation_todo_expansion",
        "direct",
    )
    assert all(
        item.source_bibliography_observation_id is None
        for item in snapshot.bibliography_entries
    )
    assert snapshot.missing_keys == ()
    assert snapshot.duplicate_keys == ()
    assert snapshot.uncited_keys == ()


@pytest.mark.parametrize("literal_citekey", ("1leading", "a.", "CON"))
def test__owner_valid_literal_keys_are_not_treated_as_filenames(
    literal_citekey: str,
) -> None:
    payload = _object(json.loads(FIXTURE.read_bytes()))
    snapshot = _adapt_snapshot(_object(payload["snapshot"]))

    adapted = replace(
        snapshot.occurrences[0],
        key=literal_citekey,
    )

    assert adapted.key == literal_citekey
    with pytest.raises(PathSafetyError):
        validate_citekey(literal_citekey)


def test__owner_valid_posix_source_path_is_not_treated_as_a_portable_path() -> (
    None
):
    payload = _object(json.loads(FIXTURE.read_bytes()))
    snapshot = _adapt_snapshot(_object(payload["snapshot"]))
    source_path = "docs/publications/research-monograph/CON/source.tex"

    adapted = replace(snapshot.occurrences[0].locator, source_path=source_path)

    assert adapted.source_path == source_path
    with pytest.raises(PathSafetyError):
        validate_relative_path(source_path)


def test__target_key_and_source_path_grammar_fails_closed() -> None:
    payload = _object(json.loads(FIXTURE.read_bytes()))
    snapshot = _adapt_snapshot(_object(payload["snapshot"]))
    occurrence = snapshot.occurrences[0]
    locator = occurrence.locator

    for invalid_key in (
        "a" * (CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS + 1),
        "not:owner-grammar",
    ):
        with pytest.raises(ValueError, match="must match ASCII"):
            replace(occurrence, key=invalid_key)
    for invalid_path in (
        "a" * (CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES + 1),
        "../source.tex",
        "docs/../source.tex",
        "/absolute/source.tex",
        "docs\\source.tex",
    ):
        with pytest.raises(ValueError, match="relative POSIX path"):
            replace(locator, source_path=invalid_path)


def test__corrected_ksdft_result__shares_exact_adapter_bounds() -> None:
    assert OWNER_COMMIT == "3ec21b4318020d700be671a8f220b2149b3d28c7"
    assert OWNER_TREE == "9953c0e99a28443426b5093852292f7cfbada2cc"
    assert CITATION_DOCUMENT_MAX_ID_BYTES == 512
    assert CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS == 200
    assert CITATION_DOCUMENT_MAX_TEXT_BYTES == 4_096
    assert CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES == 4_096
    assert CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES == 100_000_000
    assert CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES == 100_000_000
    assert CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD == 256
    assert CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES == 10_000
    assert CITATION_DOCUMENT_MAX_TARGET_RECORDS == 10_000
    assert CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES == 20_000_000
