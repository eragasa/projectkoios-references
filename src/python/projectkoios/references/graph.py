from __future__ import annotations

import csv
from pathlib import Path

from projectkoios.references.models import CitationCandidate, CitationEdge


def load_candidate_graph(
    nodes_path: Path,
    edges_path: Path,
) -> tuple[tuple[CitationCandidate, ...], tuple[CitationEdge, ...]]:
    with nodes_path.open(encoding="utf-8", newline="") as stream:
        candidates = tuple(
            CitationCandidate(
                candidate_id=row["candidate_id"],
                proposed_citekey=row.get("proposed_citekey") or None,
                title=row.get("title") or None,
                authors=row.get("authors") or None,
                year=row.get("year") or None,
                doi=row.get("doi") or None,
                metadata_status=row["metadata_status"],
                abstract_status=row["abstract_status"],
                abstract=row.get("abstract") or None,
            )
            for row in csv.DictReader(stream)
        )

    with edges_path.open(encoding="utf-8", newline="") as stream:
        edges = tuple(
            CitationEdge(
                source_id=row["source_id"],
                target_id=row["target_id"],
                relation=row["relation"],
                source_locator=row["source_locator"],
                verification_status=row["verification_status"],
            )
            for row in csv.DictReader(stream)
        )

    candidate_ids = {candidate.candidate_id for candidate in candidates}
    missing = sorted(
        edge.target_id for edge in edges if edge.target_id not in candidate_ids
    )
    if missing:
        raise ValueError(
            f"citation edges have missing candidate nodes: {missing}"
        )
    return candidates, edges
