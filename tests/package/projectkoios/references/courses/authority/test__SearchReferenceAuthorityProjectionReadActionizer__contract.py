"""Strict persisted Search authority projection loading tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from projectkoios.base import DataObjectActionizer
from projectkoios.references.courses.authority.errors import (
    CourseReferenceAuthorityError,
)
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjection,
    SearchReferenceAuthorityProjectionBytesReadResult,
    SearchReferenceAuthorityProjectionReadActionizer,
    SearchReferenceAuthorityProjectionReadRequest,
)

_FIXTURE = (
    Path(__file__).parents[5]
    / "fixtures"
    / "search-reference-authority-projection.json"
)
_PROJECTION_ID = (
    "search-reference-authority-projection:sha256:"
    "4bfe2c6354f74bfa8501cfcc7546db32311ee69f6a81ea0e075dd3919b358302"
)
_PROJECTION_RESULT_ID = (
    "search-reference-authority-result:sha256:"
    "3b6857b84357d731b276204eb38d9352d51d66b7476c344c1aedefb0270a49e5"
)


class MemorySearchAuthorityBytesSource:
    """Supply immutable fixture bytes to the core read leaf."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    def action(
        self,
        *,
        request: SearchReferenceAuthorityProjectionReadRequest,
    ) -> SearchReferenceAuthorityProjectionBytesReadResult:
        """Return bytes correlated to the request."""
        return SearchReferenceAuthorityProjectionBytesReadResult(
            request_id=request.request_id,
            content=self.content,
        )


def _request(content: bytes) -> SearchReferenceAuthorityProjectionReadRequest:
    return SearchReferenceAuthorityProjectionReadRequest(
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_size=len(content),
        expected_projection_id=_PROJECTION_ID,
        expected_projection_result_id=_PROJECTION_RESULT_ID,
    )


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _read(content: bytes) -> SearchReferenceAuthorityProjection:
    return (
        SearchReferenceAuthorityProjectionReadActionizer(
            source=MemorySearchAuthorityBytesSource(content)
        )
        .action(request=_request(content))
        .projection
    )


def test__projection_read__is_actionizer() -> None:
    assert issubclass(
        SearchReferenceAuthorityProjectionReadActionizer,
        DataObjectActionizer,
    )


def test__projection_read__round_trips_canonical_fixture() -> None:
    content = _FIXTURE.read_bytes()

    projection = _read(content)

    assert type(projection) is SearchReferenceAuthorityProjection
    assert projection.projection_id == _PROJECTION_ID
    assert projection.result_id == _PROJECTION_RESULT_ID
    assert projection.bindings[0].accepted_citekey == "Synthetic1994"


def test__projection_read__replays_deterministically() -> None:
    content = _FIXTURE.read_bytes()
    actionizer = SearchReferenceAuthorityProjectionReadActionizer(
        source=MemorySearchAuthorityBytesSource(content)
    )
    request = _request(content)

    first = actionizer.action(request=request)
    second = actionizer.action(request=request)

    assert first == second
    assert first.result_id == second.result_id


@pytest.mark.parametrize("mutation", ("duplicate", "unknown", "missing"))
def test__projection_read__rejects_nonclosed_objects(
    mutation: str,
) -> None:
    content = _FIXTURE.read_bytes()
    if mutation == "duplicate":
        changed = content.replace(
            b'{\n  "bindings": [',
            b'{\n  "bindings": [],\n  "bindings": [',
            1,
        )
    else:
        value = json.loads(content)
        if mutation == "unknown":
            value["unknown"] = "not-authoritative"
        else:
            del value["review_projection_id"]
        changed = _canonical(value)

    with pytest.raises(CourseReferenceAuthorityError):
        _read(changed)


def test__projection_read__rejects_noncanonical_json() -> None:
    value = json.loads(_FIXTURE.read_bytes())
    changed = json.dumps(value, sort_keys=True).encode("utf-8")

    with pytest.raises(
        CourseReferenceAuthorityError,
        match="not canonical",
    ):
        _read(changed)


@pytest.mark.parametrize(
    "target",
    ("link_id", "binding_id", "projection_id", "result_id"),
)
def test__projection_read__rejects_tampered_derived_ids(
    target: str,
) -> None:
    value = json.loads(_FIXTURE.read_bytes())
    replacement = "tampered:sha256:" + "d" * 64
    if target == "link_id":
        value["bindings"][0]["ingestion_artifact_links"][0][target] = (
            replacement
        )
    elif target == "binding_id":
        value["bindings"][0][target] = replacement
    else:
        value[target] = replacement

    with pytest.raises(
        CourseReferenceAuthorityError,
        match=f"supplied {target}",
    ):
        _read(_canonical(value))


def test__projection_read__rejects_noncanonical_nested_order() -> None:
    value = json.loads(_FIXTURE.read_bytes())
    evidence = value["bindings"][0]["authority_evidence_ids"]
    value["bindings"][0]["authority_evidence_ids"] = list(reversed(evidence))

    with pytest.raises(
        CourseReferenceAuthorityError,
        match="lexical order",
    ):
        _read(_canonical(value))


def test__projection_read__verifies_length_before_decode() -> None:
    content = _FIXTURE.read_bytes()
    request = SearchReferenceAuthorityProjectionReadRequest(
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_size=len(content) - 1,
        expected_projection_id=_PROJECTION_ID,
        expected_projection_result_id=_PROJECTION_RESULT_ID,
    )

    with pytest.raises(
        CourseReferenceAuthorityError,
        match="byte length",
    ):
        SearchReferenceAuthorityProjectionReadActionizer(
            source=MemorySearchAuthorityBytesSource(content)
        ).action(request=request)


def test__projection_read__verifies_sha_before_decode() -> None:
    content = _FIXTURE.read_bytes()
    request = SearchReferenceAuthorityProjectionReadRequest(
        expected_sha256="f" * 64,
        expected_byte_size=len(content),
        expected_projection_id=_PROJECTION_ID,
        expected_projection_result_id=_PROJECTION_RESULT_ID,
    )

    with pytest.raises(
        CourseReferenceAuthorityError,
        match="SHA-256",
    ):
        SearchReferenceAuthorityProjectionReadActionizer(
            source=MemorySearchAuthorityBytesSource(content)
        ).action(request=request)
