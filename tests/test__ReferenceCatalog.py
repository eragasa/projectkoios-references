from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from projectkoios.references.catalog import (
    CandidateConflictError,
    ReferenceCatalog,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import (
    CitationCandidate,
    CitationEdge,
    ReviewMembership,
    ReviewStatus,
    SourceAssetRecord,
)


def _observed_candidate(
    *,
    citekey: str = "jensenKristensen2009",
    title: str = "Coloured Petri Nets",
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
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("fixture-normalizer", "1"),
    )
    return observation, candidate


def test__catalog__projects_bibliography_candidates_without_acceptance(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    observation, candidate = _observed_candidate()
    catalog.import_candidates((candidate,), (observation,))
    catalog.record_source_asset(
        SourceAssetRecord(
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
    )
    catalog.set_review_membership(
        ReviewMembership(
            collection_id="workflow",
            citekey=candidate.proposed_citekey,
            status=ReviewStatus.METADATA_VERIFIED,
        )
    )
    catalog.import_citation_graph(
        (
            CitationCandidate(
                candidate_id="fixture.ref01",
                proposed_citekey="padberg2014",
                title="Reconfigurable Decorated PT Nets",
                authors="Julia Padberg",
                year="2014",
                doi=None,
                metadata_status="transcribed",
                abstract_status="not-requested",
            ),
        ),
        (
            CitationEdge(
                source_id=candidate.candidate_id,
                target_id="fixture.ref01",
                relation="cites",
                source_locator="References [1]",
                verification_status="verified-in-source",
            ),
        ),
    )

    assert candidate.lifecycle_status == "unaccepted-candidate"
    assert catalog.counts() == {
        "candidate_records": 1,
        "unprovenanced_alias_rows": 0,
        "bibliography_observations": 1,
        "source_assets": 1,
        "review_memberships": 1,
        "abstracts": 0,
        "citation_candidates": 1,
        "citation_edges": 1,
    }
    with sqlite3.connect(catalog.path) as connection:
        candidate_row = connection.execute(
            """
            SELECT lifecycle_status, citekey_status, candidate_json
            FROM reference_candidates
            """
        ).fetchone()
        observation_json = connection.execute(
            "SELECT observation_json FROM source_bibliography_observations"
        ).fetchone()[0]
        asset_status = connection.execute(
            """
            SELECT identity_status, citekey_status
            FROM candidate_source_assets
            """
        ).fetchone()
    assert candidate_row[:2] == (
        "unaccepted-candidate",
        "proposed-noncanonical",
    )
    assert (
        json.loads(candidate_row[2])["candidate_id"] == candidate.candidate_id
    )
    assert json.loads(observation_json)["verbatim_entry"] == (
        observation.verbatim_entry
    )
    assert asset_status == (
        "unaccepted-candidate",
        "proposed-noncanonical",
    )


def test__catalog__rejects_conflicting_candidate_projection(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    first_observation, first = _observed_candidate(
        citekey="example2020",
        title="First title",
    )
    conflicting_observation, conflicting = _observed_candidate(
        citekey="example2020",
        title="Conflicting title",
    )
    catalog.import_candidates((first,), (first_observation,))

    with pytest.raises(CandidateConflictError, match="candidate metadata"):
        catalog.import_candidates(
            (conflicting,),
            (conflicting_observation,),
        )
