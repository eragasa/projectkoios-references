import csv
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_GRAPH = _PROJECT_ROOT / "collections/projectkoios-workflow/padbergHoffmann2015"


def _rows(filename: str) -> list[dict[str, str]]:
    with (_GRAPH / filename).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test__padberg_graph__records_each_direct_reference_once() -> None:
    nodes = _rows("nodes.csv")
    edges = _rows("edges.csv")

    node_ids = {node["candidate_id"] for node in nodes}
    assert len(nodes) == len(node_ids) == 34
    assert len(edges) == 34
    assert {edge["target_id"] for edge in edges} == node_ids
    assert {edge["source_id"] for edge in edges} == {"padbergHoffmann2015"}


def test__padberg_graph__does_not_invent_missing_abstracts() -> None:
    nodes = _rows("nodes.csv")

    for node in nodes:
        if not node["abstract"]:
            assert node["abstract_status"] in {
                "not-available-in-crossref",
                "not-requested",
            }
