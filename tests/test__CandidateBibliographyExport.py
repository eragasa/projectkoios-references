from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from projectkoios.references import candidate_bibliography as contract
from projectkoios.references.biblatex import load_bibliography
from projectkoios.references.candidate_bibliography import (
    CandidateBibliographyExporter,
    CandidateBibliographyExportError,
    CandidateBibliographyExportRequest,
    CandidateBibliographyExportResult,
    CandidateBibliographyExportStatus,
    CandidateBibliographySourceDeclaration,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    SourceBibliographyObservation,
)
from projectkoios.references.path_safety import RootStorageClass

_FIXTURES = Path(__file__).parent / "fixtures" / "candidate-bibliography"


def _declaration(
    filename: str,
    *,
    collection_id: str,
) -> CandidateBibliographySourceDeclaration:
    path = _FIXTURES / filename
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    imported = load_bibliography(
        path,
        source_id=f"sanitized-test:{collection_id}",
        source_revision=f"sha256:{digest}",
        source_path=f"fixtures/{filename}",
        storage_class=RootStorageClass.LOCAL,
    )
    return CandidateBibliographySourceDeclaration(
        collection_id=collection_id,
        observations=imported.observations,
    )


def _request() -> CandidateBibliographyExportRequest:
    return CandidateBibliographyExportRequest(
        sources=(
            _declaration(
                "materials-course.bib",
                collection_id="materials-course",
            ),
            _declaration(
                "devices-course.bib",
                collection_id="devices-course",
            ),
        )
    )


def test__candidate_bibliography_export__is_exact_deterministic_union() -> None:
    request = _request()
    exporter = CandidateBibliographyExporter()

    result = exporter.action(request=request)
    reversed_result = exporter.export(
        request=CandidateBibliographyExportRequest(
            sources=tuple(reversed(request.sources))
        )
    )
    expected = (_FIXTURES / "expected-union.bib").read_bytes()

    assert result.bibliography == expected
    assert result.citekeys == (
        "deviceExample2026",
        "materialsExample2024",
        "sharedMethod2025",
        "transportExample2023",
    )
    assert result.status is (
        CandidateBibliographyExportStatus.PROPOSED_NONCANONICAL
    )
    assert result.bibliography_byte_size == len(expected)
    assert result.bibliography_sha256 == hashlib.sha256(expected).hexdigest()
    assert tuple(item.collection_id for item in result.provenance) == (
        "devices-course",
        "materials-course",
    )
    assert all(
        item.asserted_source_revision == f"sha256:{item.bibliography_sha256}"
        for item in result.provenance
    )
    assert reversed_result.bibliography == result.bibliography
    assert reversed_result.provenance == result.provenance
    assert reversed_result.request.request_id == result.request.request_id
    assert reversed_result.result_id == result.result_id

    observed_entries = {
        observation.observed_citekey: observation.verbatim_entry.encode("utf-8")
        for source in request.sources
        for observation in source.observations
    }
    assert all(
        entry in result.bibliography for entry in observed_entries.values()
    )


def test__candidate_bibliography_export__deduplicates_entries() -> None:
    materials = _declaration(
        "materials-course.bib",
        collection_id="materials-course",
    )
    duplicate = _declaration(
        "duplicate-shared.bib",
        collection_id="shared-course",
    )

    result = CandidateBibliographyExporter().export(
        request=CandidateBibliographyExportRequest(
            sources=(duplicate, materials)
        )
    )

    assert result.citekeys == (
        "materialsExample2024",
        "sharedMethod2025",
    )
    assert result.bibliography.count(b"@article{sharedMethod2025,") == 1
    assert tuple(item.collection_id for item in result.provenance) == (
        "materials-course",
        "shared-course",
    )


def test__candidate_bibliography_export__rejects_citekey_collision() -> None:
    request = CandidateBibliographyExportRequest(
        sources=(
            _declaration("collision-a.bib", collection_id="source-a"),
            _declaration("collision-b.bib", collection_id="source-b"),
        )
    )

    with pytest.raises(
        CandidateBibliographyExportError,
        match="citekey collision: collidingExample",
    ):
        CandidateBibliographyExporter().export(request=request)


def test__candidate_export__rejects_duplicate_collections() -> None:
    declaration = _declaration(
        "materials-course.bib",
        collection_id="materials-course",
    )

    with pytest.raises(
        CandidateBibliographyExportError,
        match="duplicate collection IDs",
    ):
        CandidateBibliographyExportRequest(sources=(declaration, declaration))


def test__candidate_export__rejects_mixed_source_provenance() -> None:
    materials = _declaration(
        "materials-course.bib",
        collection_id="materials-course",
    )
    devices = _declaration(
        "devices-course.bib",
        collection_id="devices-course",
    )

    with pytest.raises(
        CandidateBibliographyExportError,
        match="mixed provenance",
    ):
        CandidateBibliographySourceDeclaration(
            collection_id="mixed-course",
            observations=(
                materials.observations[0],
                devices.observations[1],
            ),
        )


def test__candidate_bibliography_export__rejects_entry_key_mismatch() -> None:
    bibliography = b"@book{declaredKey, title={Sanitized}}\n"
    verbatim = bibliography.decode("utf-8").rstrip("\n")
    observation = SourceBibliographyObservation.create(
        source_id="sanitized-test:mismatch",
        asserted_source_revision=(
            "sha256:" + hashlib.sha256(bibliography).hexdigest()
        ),
        source_path="fixtures/mismatch.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey="differentKey",
        verbatim_entry=verbatim,
        parser=ProducerIdentity("sanitized-parser", "1"),
    )

    with pytest.raises(
        CandidateBibliographyExportError,
        match="citekey differs",
    ):
        CandidateBibliographySourceDeclaration(
            collection_id="mismatch-course",
            observations=(observation,),
        )


def test__candidate_bibliography_export__fails_closed_on_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    monkeypatch.setattr(
        contract,
        "CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES",
        3,
    )

    with pytest.raises(
        CandidateBibliographyExportError,
        match="entry limit",
    ):
        CandidateBibliographyExporter().export(request=request)

    monkeypatch.setattr(
        contract,
        "CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_ENTRIES",
        10_000,
    )
    monkeypatch.setattr(
        contract,
        "CANDIDATE_BIBLIOGRAPHY_EXPORT_MAX_BYTES",
        10,
    )
    with pytest.raises(
        CandidateBibliographyExportError,
        match="export exceeds the byte limit",
    ):
        CandidateBibliographyExporter().export(request=request)


def test__candidate_bibliography_export__result_replays_request() -> None:
    result = CandidateBibliographyExporter().export(request=_request())

    with pytest.raises(
        CandidateBibliographyExportError,
        match="bibliography does not match",
    ):
        CandidateBibliographyExportResult(
            request=result.request,
            provenance=result.provenance,
            citekeys=result.citekeys,
            bibliography=result.bibliography + b"% changed\n",
        )
