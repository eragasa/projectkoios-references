from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references.catalog import (
    ReferenceCatalog,
    ReferenceConflictError,
)
from projectkoios.references.models import (
    BibliographyOccurrence,
    CitationCandidate,
    CitationEdge,
    ReferenceAlias,
    ReferenceRecord,
    ReviewMembership,
    ReviewStatus,
)


def test__catalog__imports_bibliography_and_candidate_graph(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    record = ReferenceRecord(
        citekey="jensenKristensen2009",
        entry_type="book",
        title="Coloured Petri Nets",
        authors=("Kurt Jensen", "Lars M. Kristensen"),
        year="2009",
        doi="10.1007/b95112",
    )
    occurrence = BibliographyOccurrence(
        citekey=record.citekey,
        source_id="fixture",
        source_revision="abc123",
        source_path="references.bib",
    )
    catalog.import_bibliography((record,), (occurrence,))
    catalog.add_alias(
        ReferenceAlias(
            alias="jensen2009",
            canonical_citekey=record.citekey,
            rationale="legacy local key",
        )
    )
    catalog.set_review_membership(
        ReviewMembership(
            collection_id="workflow",
            citekey=record.citekey,
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
                source_id=record.citekey,
                target_id="fixture.ref01",
                relation="cites",
                source_locator="References [1]",
                verification_status="verified-in-source",
            ),
        ),
    )

    assert catalog.counts() == {
        "reference_records": 1,
        "reference_aliases": 1,
        "bibliography_occurrences": 1,
        "source_assets": 0,
        "review_memberships": 1,
        "abstracts": 0,
        "citation_candidates": 1,
        "citation_edges": 1,
    }


def test__catalog__rejects_conflicting_metadata_instead_of_replacing(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "references.sqlite3")
    catalog.initialize()
    occurrence = BibliographyOccurrence(
        citekey="example2020",
        source_id="fixture",
        source_revision=None,
        source_path="references.bib",
    )
    first = ReferenceRecord(
        citekey="example2020",
        entry_type="article",
        title="First title",
        authors=("Jane Doe",),
        year="2020",
    )
    conflicting = ReferenceRecord(
        citekey="example2020",
        entry_type="article",
        title="Conflicting title",
        authors=("Jane Doe",),
        year="2020",
    )
    catalog.import_bibliography((first,), (occurrence,))

    with pytest.raises(ReferenceConflictError, match="conflicting metadata"):
        catalog.import_bibliography((conflicting,), (occurrence,))
