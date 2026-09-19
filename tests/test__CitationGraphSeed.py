from pathlib import Path

from projectkoios.references.graph import (
    load_candidate_graph as _load_candidate_graph,
)
from projectkoios.references.path_safety import RootStorageClass


def load_candidate_graph(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.update(
        sources_storage_class=RootStorageClass.LOCAL,
        nodes_storage_class=RootStorageClass.LOCAL,
        edges_storage_class=RootStorageClass.LOCAL,
    )
    return _load_candidate_graph(*args, **kwargs)  # type: ignore[arg-type]


_PROJECT_ROOT = Path(__file__).parent.parent
_GRAPH = _PROJECT_ROOT / "collections/projectkoios-workflow/padbergHoffmann2015"


def test__padberg_graph__is_source_backed_and_direct_only() -> None:
    graph = load_candidate_graph(
        _GRAPH / "sources.csv",
        _GRAPH / "nodes.csv",
        _GRAPH / "edges.csv",
    )

    assert len(graph.sources) == 1
    assert len(graph.candidates) == len(graph.edges) == 34
    source = graph.sources[0]
    assert source.source_sha256 == (
        "2d042a92d1fad7fa97921eaa2b042b3276cdfa40d9463284acb3326f5e8008ca"
    )
    assert {edge.source_observation_id for edge in graph.edges} == {
        source.source_observation_id
    }
    assert {edge.target_candidate_id for edge in graph.edges} == {
        candidate.candidate_id for candidate in graph.candidates
    }
    assert {edge.relation for edge in graph.edges} == {"cites"}


def test__padberg_graph__keeps_verbatim_fields_separate_from_proposals() -> (
    None
):
    graph = load_candidate_graph(
        _GRAPH / "sources.csv",
        _GRAPH / "nodes.csv",
        _GRAPH / "edges.csv",
    )

    for candidate in graph.candidates:
        assert candidate.lifecycle_status == "unaccepted-candidate"
        assert candidate.proposal_status == "unaccepted-normalized-proposal"
        assert candidate.verbatim_title
        assert candidate.verbatim_authors
        assert candidate.source_locator.startswith("References [")
