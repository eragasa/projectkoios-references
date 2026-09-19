from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from projectkoios.references.catalog import (
    CatalogConflictError,
    RootStorageClass,
)
from projectkoios.references.catalog import (
    ReferenceCatalog as _ReferenceCatalog,
)
from projectkoios.references.cli import main
from projectkoios.references.graph import (
    CitationCandidate,
    CitationEdge,
    CitationGraph,
    CitationGraphError,
    CitationSourceObservation,
    GraphImportLimits,
)
from projectkoios.references.graph import (
    load_candidate_graph as _load_candidate_graph,
)


def load_candidate_graph(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.update(
        sources_storage_class=RootStorageClass.LOCAL,
        nodes_storage_class=RootStorageClass.LOCAL,
        edges_storage_class=RootStorageClass.LOCAL,
    )
    return _load_candidate_graph(*args, **kwargs)  # type: ignore[arg-type]


def ReferenceCatalog(path: Path) -> _ReferenceCatalog:
    return _ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)


def _source(
    *, revision: str = "revision-1", digest: str = "a" * 64
) -> CitationSourceObservation:
    return CitationSourceObservation.create(
        source_id="fixture-parent",
        asserted_source_revision=revision,
        source_path="sources/parent.pdf",
        source_sha256=digest,
        source_byte_size=1234,
    )


def _candidate(
    source: CitationSourceObservation,
    *,
    locator: str = "References [1], p. 10",
    title: str = "  Verbatim Title: α  ",
) -> CitationCandidate:
    return CitationCandidate.create(
        source_observation_id=source.source_observation_id,
        source_locator=locator,
        verbatim_entry="Ada Example.  Verbatim Title: α. DOI:10.1000/ABC.",
        verbatim_identifier="DOI:10.1000/ABC",
        verbatim_title=title,
        verbatim_authors="Example, Ada",
        proposed_citekey="example2026",
        proposed_container_or_type="article",
        proposed_title="Verbatim Title: α",
        proposed_authors=("Ada Example",),
        proposed_year="2026",
        proposed_doi="https://doi.org/10.1000/ABC",
    )


def _graph(
    *,
    source: CitationSourceObservation | None = None,
    locator: str = "References [1], p. 10",
    title: str = "  Verbatim Title: α  ",
) -> CitationGraph:
    parent = source or _source()
    candidate = _candidate(parent, locator=locator, title=title)
    edge = CitationEdge.create(
        source_observation_id=parent.source_observation_id,
        target_candidate_id=candidate.candidate_id,
        source_locator=candidate.source_locator,
    )
    return CitationGraph.create(
        sources=(parent,),
        candidates=(candidate,),
        edges=(edge,),
    )


def _write_graph_csv(
    root: Path, graph: CitationGraph
) -> tuple[Path, Path, Path]:
    sources = root / "sources.csv"
    nodes = root / "nodes.csv"
    edges = root / "edges.csv"
    with sources.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
                "source_observation_id",
                "source_id",
                "asserted_source_revision",
                "source_path",
                "source_sha256",
                "source_byte_size",
            )
        )
        for source in graph.sources:
            writer.writerow(
                (
                    source.source_observation_id,
                    source.source_id,
                    source.asserted_source_revision or "",
                    source.source_path,
                    source.source_sha256,
                    source.source_byte_size,
                )
            )
    with nodes.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
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
        )
        for candidate in graph.candidates:
            writer.writerow(
                (
                    candidate.candidate_id,
                    candidate.source_observation_id,
                    candidate.source_locator,
                    candidate.verbatim_entry or "",
                    candidate.verbatim_identifier or "",
                    candidate.verbatim_title or "",
                    candidate.verbatim_authors or "",
                    candidate.proposed_citekey or "",
                    candidate.proposed_container_or_type or "",
                    candidate.proposed_title or "",
                    json.dumps(
                        candidate.proposed_authors,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    candidate.proposed_year or "",
                    candidate.proposed_doi or "",
                )
            )
    with edges.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            (
                "edge_id",
                "source_observation_id",
                "target_candidate_id",
                "relation",
                "source_locator",
            )
        )
        for edge in graph.edges:
            writer.writerow(
                (
                    edge.edge_id,
                    edge.source_observation_id,
                    edge.target_candidate_id,
                    edge.relation,
                    edge.source_locator,
                )
            )
    return sources, nodes, edges


def test__graph__identity_tracks_source_revision_content_and_locator() -> None:
    first = _graph()
    replay = _graph()
    revised = _graph(source=_source(revision="revision-2"))
    changed_blob = _graph(source=_source(digest="b" * 64))
    moved = _graph(locator="References [2], p. 11")

    assert first == replay
    assert first.sources[0].source_observation_id != (
        revised.sources[0].source_observation_id
    )
    assert first.sources[0].source_observation_id != (
        changed_blob.sources[0].source_observation_id
    )
    assert first.candidates[0].candidate_id != moved.candidates[0].candidate_id
    assert first.edges[0].edge_id != moved.edges[0].edge_id


def test__graph__preserves_verbatim_evidence_without_promoting_proposals() -> (
    None
):
    graph = _graph()
    candidate = graph.candidates[0]

    assert candidate.verbatim_identifier == "DOI:10.1000/ABC"
    assert candidate.verbatim_title == "  Verbatim Title: α  "
    assert candidate.verbatim_authors == "Example, Ada"
    assert candidate.source_locator == "References [1], p. 10"
    assert candidate.proposed_doi == "10.1000/abc"
    assert candidate.lifecycle_status == "unaccepted-candidate"
    assert candidate.proposal_status == "unaccepted-normalized-proposal"
    assert graph.edges[0].evidence_status == "source-observed-only"
    assert "no-membership-or-acceptance-authority" in graph.to_json()


def test__graph__rejects_orphan_and_crossed_domains() -> None:
    graph = _graph()
    source = graph.sources[0]
    candidate = graph.candidates[0]
    orphan_source = _source(revision="orphan")
    orphan_edge = CitationEdge.create(
        source_observation_id=orphan_source.source_observation_id,
        target_candidate_id=candidate.candidate_id,
        source_locator=candidate.source_locator,
    )
    with pytest.raises(CitationGraphError, match="orphan source"):
        CitationGraph.create(
            sources=(source,),
            candidates=(candidate,),
            edges=(orphan_edge,),
        )

    missing_target = CitationCandidate.identity_for(
        source_observation_id=source.source_observation_id,
        source_locator="References [missing]",
    )
    orphan_target = CitationEdge.create(
        source_observation_id=source.source_observation_id,
        target_candidate_id=missing_target,
        source_locator="References [missing]",
    )
    with pytest.raises(CitationGraphError, match="orphan candidate target"):
        CitationGraph.create(
            sources=(source,),
            candidates=(candidate,),
            edges=(orphan_target,),
        )

    other_candidate = _candidate(source, locator="References [2]")
    crossed = CitationEdge.create(
        source_observation_id=source.source_observation_id,
        target_candidate_id=other_candidate.candidate_id,
        source_locator="References [3]",
    )
    with pytest.raises(CitationGraphError, match="differs from"):
        CitationGraph.create(
            sources=(source,),
            candidates=(other_candidate,),
            edges=(crossed,),
        )


def test__graph__direct_construction_enforces_complete_domains() -> None:
    source = _source()
    candidate = _candidate(source)

    with pytest.raises(CitationGraphError, match="require candidates"):
        CitationGraph(
            sources=(source,),
            candidates=(),
            edges=(),
        )
    with pytest.raises(CitationGraphError, match="without direct edges"):
        CitationGraph(
            sources=(source,),
            candidates=(candidate,),
            edges=(),
        )
    with pytest.raises(CitationGraphError, match="require a source"):
        CitationGraph(
            sources=(),
            candidates=(candidate,),
            edges=(),
        )
    crossed = CitationEdge.create(
        source_observation_id=source.source_observation_id,
        target_candidate_id=candidate.candidate_id,
        source_locator="References [crossed]",
    )
    with pytest.raises(CitationGraphError, match="differs from"):
        CitationGraph(
            sources=(source,),
            candidates=(candidate,),
            edges=(crossed,),
        )
    with pytest.raises(CitationGraphError, match="require candidates"):
        CitationGraph.create(
            sources=(source,),
            candidates=(),
            edges=(),
        )

    assert CitationGraph.create(sources=(), candidates=(), edges=()) == (
        CitationGraph(sources=(), candidates=(), edges=())
    )


def test__graph__rejects_duplicate_rows_and_breadth() -> None:
    graph = _graph()
    with pytest.raises(CitationGraphError, match="duplicate candidate"):
        CitationGraph.create(
            sources=graph.sources,
            candidates=graph.candidates * 2,
            edges=graph.edges,
        )

    source = graph.sources[0]
    second = _candidate(source, locator="References [2]")
    second_edge = CitationEdge.create(
        source_observation_id=source.source_observation_id,
        target_candidate_id=second.candidate_id,
        source_locator=second.source_locator,
    )
    with pytest.raises(CitationGraphError, match="breadth"):
        CitationGraph.create(
            sources=(source,),
            candidates=(graph.candidates[0], second),
            edges=(graph.edges[0], second_edge),
            limits=GraphImportLimits(max_breadth_per_source=1),
        )
    with pytest.raises(CitationGraphError, match="candidate rows"):
        CitationGraph.create(
            sources=(source,),
            candidates=(graph.candidates[0], second),
            edges=(graph.edges[0], second_edge),
            limits=GraphImportLimits(max_candidates=1),
        )


def test__graph_limits__cannot_raise_public_hard_ceiling() -> None:
    assert GraphImportLimits(max_total_bytes=4_000_000).max_total_bytes == (
        4_000_000
    )
    with pytest.raises(CitationGraphError, match="no greater than 4000000"):
        GraphImportLimits(max_total_bytes=4_000_001)


def test__graph_csv__is_bounded_strict_and_deterministic(
    tmp_path: Path,
) -> None:
    expected = _graph()
    paths = _write_graph_csv(tmp_path, expected)

    loaded = load_candidate_graph(*paths)
    assert loaded == expected
    payload = json.loads(loaded.to_json())
    assert len(payload["root_preflights"]) == 3
    assert str(tmp_path) not in loaded.to_json()

    with pytest.raises(CitationGraphError, match="byte limit"):
        load_candidate_graph(
            *paths,
            limits=GraphImportLimits(
                max_file_bytes=100,
                max_total_bytes=300,
            ),
        )
    total_size = sum(path.stat().st_size for path in paths)
    with pytest.raises(CitationGraphError, match="total byte limit"):
        load_candidate_graph(
            *paths,
            limits=GraphImportLimits(max_total_bytes=total_size - 1),
        )

    nodes = paths[1]
    nodes.write_text('candidate_id,source_observation_id\n"unterminated\n')
    with pytest.raises(CitationGraphError, match="header|malformed"):
        load_candidate_graph(*paths)


def test__graph_csv__rejects_duplicate_and_oversized_text(
    tmp_path: Path,
) -> None:
    graph = _graph()
    paths = _write_graph_csv(tmp_path, graph)
    with paths[0].open("a", encoding="utf-8") as handle:
        row = graph.sources[0]
        handle.write(
            f"{row.source_observation_id},{row.source_id},"
            f"{row.asserted_source_revision},{row.source_path},"
            f"{row.source_sha256},{row.source_byte_size}\n"
        )
    with pytest.raises(CitationGraphError, match="duplicate source"):
        load_candidate_graph(*paths)

    paths = _write_graph_csv(tmp_path, graph)
    text = paths[1].read_text(encoding="utf-8")
    paths[1].write_text(
        text.replace("  Verbatim Title: α  ", "x" * 4_097),
        encoding="utf-8",
    )
    with pytest.raises(CitationGraphError, match="text byte limit"):
        load_candidate_graph(*paths)


def test__graph_cli__invalid_batch_does_not_create_catalog(
    tmp_path: Path,
) -> None:
    paths = _write_graph_csv(tmp_path, _graph())
    paths[1].write_text('candidate_id,source_observation_id\n"unterminated\n')
    catalog_path = tmp_path / "absent.sqlite3"

    with pytest.raises(CitationGraphError, match="header|malformed"):
        main(
            [
                "graph-import",
                str(catalog_path),
                *(str(path) for path in paths),
                "--catalog-storage-class",
                "local",
                "--sources-storage-class",
                "local",
                "--nodes-storage-class",
                "local",
                "--edges-storage-class",
                "local",
            ]
        )

    assert not catalog_path.exists()


def test__catalog__rejects_source_only_without_mutation_and_empty_is_noop(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "catalog.sqlite3")
    catalog.initialize()
    before = catalog.counts()
    catalog.import_citation_graph(
        CitationGraph.create(sources=(), candidates=(), edges=())
    )
    assert catalog.counts() == before

    invalid = object.__new__(CitationGraph)
    object.__setattr__(invalid, "sources", (_source(),))
    object.__setattr__(invalid, "candidates", ())
    object.__setattr__(invalid, "edges", ())
    with pytest.raises(CitationGraphError, match="require candidates"):
        catalog.import_citation_graph(invalid)
    assert catalog.counts() == before


def test__catalog__source_change_appends_and_retains_history(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "catalog.sqlite3")
    catalog.initialize()
    first = _graph()
    revised = _graph(source=_source(revision="revision-2", digest="b" * 64))

    catalog.import_citation_graph(first)
    catalog.import_citation_graph(revised)

    stored = catalog.read_citation_graph()
    assert set(stored.sources) == {first.sources[0], revised.sources[0]}
    assert set(stored.candidates) == {
        first.candidates[0],
        revised.candidates[0],
    }
    assert set(stored.edges) == {first.edges[0], revised.edges[0]}


def test__catalog__late_graph_conflict_rolls_back_all_new_rows(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "catalog.sqlite3")
    catalog.initialize()
    first = _graph()
    catalog.import_citation_graph(first)
    before = catalog.counts()

    changed_existing = _candidate(
        first.sources[0],
        title="Conflicting transcription",
    )
    second_source = _source(revision="revision-2", digest="b" * 64)
    second_candidate = _candidate(second_source)
    batch = CitationGraph.create(
        sources=(first.sources[0], second_source),
        candidates=(changed_existing, second_candidate),
        edges=(
            CitationEdge.create(
                source_observation_id=first.sources[0].source_observation_id,
                target_candidate_id=changed_existing.candidate_id,
                source_locator=changed_existing.source_locator,
            ),
            CitationEdge.create(
                source_observation_id=second_source.source_observation_id,
                target_candidate_id=second_candidate.candidate_id,
                source_locator=second_candidate.source_locator,
            ),
        ),
    )

    with pytest.raises(CatalogConflictError, match="existing evidence"):
        catalog.import_citation_graph(batch)

    assert catalog.counts() == before
    assert catalog.read_citation_graph() == first
