from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references.catalog import (
    CatalogConflictError,
    CatalogSchemaError,
)
from projectkoios.references.catalog import (
    ReferenceCatalog as _ReferenceCatalog,
)
from projectkoios.references.graph import (
    CitationCandidate,
    CitationEdge,
    CitationGraph,
    CitationSourceObservation,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.path_safety import RootStorageClass


def ReferenceCatalog(path: Path) -> _ReferenceCatalog:
    return _ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)


def _observed_candidate(
    *,
    citekey: str = "jensenKristensen2009",
    title: str = "Coloured Petri Nets",
    url: str | None = "https://example.test/reference",
    eprint: str | None = "arXiv:2601.00001",
) -> tuple[SourceBibliographyObservation, ReferenceCandidate]:
    bibliography = (
        f"@book{{{citekey}, title={{{title}}}, year={{2009}}}}\n"
    ).encode()
    observation = SourceBibliographyObservation.create(
        source_id="fixture",
        asserted_source_revision="abc123",
        source_path="references.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey=citekey,
        verbatim_entry=bibliography.decode().strip(),
        parser=ProducerIdentity("fixture-parser", "1"),
    )
    candidate = ReferenceCandidate.create(
        proposed_citekey=citekey,
        entry_type="book",
        title=title,
        authors=("Kurt Jensen", "Lars M. Kristensen"),
        year="2009",
        doi="10.1007/b95112",
        url=url,
        eprint=eprint,
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("fixture-normalizer", "1"),
    )
    return observation, candidate


def test__catalog__round_trips_complete_identity_records(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    schema = catalog.initialize()
    observation, candidate = _observed_candidate()

    catalog.import_candidates((candidate,), (observation,))
    first_export = catalog.export_identity_json()
    catalog.import_candidates((candidate,), (observation,))

    assert catalog.schema_info() == schema
    assert catalog.read_observations() == (observation,)
    assert catalog.read_candidates() == (candidate,)
    assert catalog.export_identity_json() == first_export
    assert json.loads(first_export)["authority_boundary"] == (
        "non-authoritative-rebuildable-working-projection"
    )
    assert catalog.counts() == {
        "candidate_records": 1,
        "bibliography_observations": 1,
        "source_assets": 0,
        "legacy_reference_rows": 0,
        "unprovenanced_alias_rows": 0,
        "review_memberships": 0,
        "technical_review_records": 0,
        "human_review_decisions": 0,
        "state_projections": 0,
        "abstracts": 0,
        "citation_source_observations": 0,
        "citation_candidates": 0,
        "citation_edges": 0,
        "legacy_citation_candidates": 0,
        "legacy_citation_edges": 0,
    }

    with sqlite3.connect(catalog.path) as connection:
        row = connection.execute(
            """
            SELECT url, eprint, candidate_json
            FROM reference_candidates
            """
        ).fetchone()
    assert row[:2] == (candidate.url, candidate.eprint)
    assert row[2] == candidate.to_json()


def test__catalog__keeps_same_proposed_key_as_distinct_candidates(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    first_observation, first = _observed_candidate(title="First title")
    second_observation, second = _observed_candidate(title="Second title")

    catalog.import_candidates(
        (first, second),
        (first_observation, second_observation),
    )

    assert first.candidate_id != second.candidate_id
    assert catalog.read_candidates() == tuple(
        sorted((first, second), key=lambda item: item.candidate_id)
    )
    assert catalog.counts()["legacy_reference_rows"] == 0


def test__catalog__source_assets_are_append_only_and_transactional(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    observation, candidate = _observed_candidate()
    catalog.import_candidates((candidate,), (observation,))
    first = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="a" * 64,
        byte_size=42,
        root_alias="papers",
        relative_path="candidate.pdf",
        rights_status="unreviewed",
        asset_status="located-candidate",
    )
    conflicting = SourceAssetRecord(
        candidate_id=candidate.candidate_id,
        proposed_citekey=candidate.proposed_citekey,
        identity_status=candidate.lifecycle_status,
        citekey_status=candidate.citekey_status,
        sha256="a" * 64,
        byte_size=42,
        root_alias="papers",
        relative_path="different.pdf",
        rights_status="unreviewed",
        asset_status="located-candidate",
    )

    catalog.record_source_asset(first)
    catalog.record_source_asset(first)
    with pytest.raises(CatalogConflictError, match="existing evidence"):
        catalog.record_source_assets((conflicting,))

    assert catalog.counts()["source_assets"] == 1
    assert catalog.read_source_assets() == (first,)
    assert catalog.read_source_assets(max_records=1) == (first,)
    second = replace(
        first,
        sha256="b" * 64,
        relative_path="second-candidate.pdf",
    )
    catalog.record_source_asset(second)
    with pytest.raises(CatalogSchemaError, match="exceed the requested limit"):
        catalog.read_source_assets(max_records=1)
    with pytest.raises(ValueError, match="positive integer"):
        catalog.read_source_assets(max_records=0)


def _citation_graph(*, title: str = "Source title") -> CitationGraph:
    source = CitationSourceObservation.create(
        source_id="fixture-parent",
        asserted_source_revision="revision-1",
        source_path="parent.pdf",
        source_sha256="f" * 64,
        source_byte_size=100,
    )
    candidate = CitationCandidate.create(
        source_observation_id=source.source_observation_id,
        source_locator="References [1]",
        verbatim_title=title,
        verbatim_authors="Ada Example",
        proposed_citekey="example2026",
        proposed_title=title,
        proposed_authors=("Ada Example",),
        proposed_year="2026",
        proposed_doi="10.1000/example",
    )
    edge = CitationEdge.create(
        source_observation_id=source.source_observation_id,
        target_candidate_id=candidate.candidate_id,
        source_locator=candidate.source_locator,
    )
    return CitationGraph.create(
        sources=(source,),
        candidates=(candidate,),
        edges=(edge,),
    )


def test__catalog__graph_replay_is_idempotent_and_conflicts_fail(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    graph = _citation_graph()
    catalog.import_citation_graph(graph)
    first_export = catalog.export_citation_graph_json()
    catalog.import_citation_graph(graph)

    conflicting = _citation_graph(title="Changed source title")
    with pytest.raises(CatalogConflictError, match="existing evidence"):
        catalog.import_citation_graph(conflicting)

    assert catalog.read_citation_graph() == graph
    assert catalog.export_citation_graph_json() == first_export
    assert catalog.counts()["citation_source_observations"] == 1
    assert catalog.counts()["citation_candidates"] == 1
    assert catalog.counts()["citation_edges"] == 1
