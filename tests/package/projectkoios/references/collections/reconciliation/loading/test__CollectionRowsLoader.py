from __future__ import annotations

from pathlib import Path

from projectkoios.references.collections.reconciliation.loading import (
    CollectionRowsLoader,
    CollectionRowsLoadRequest,
    CollectionRowsLoadResult,
)
from projectkoios.references.path_safety import RootStorageClass


def test__CollectionRowsLoader__returns_deterministic_typed_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "collection.csv"
    path.write_text(
        "citekey,source_bibliographies,bibliographic_status,reading_status\n"
        "beta2021,secondary.bib,unverified,unread\n"
        "alpha2020,references.bib,verified,read\n",
        encoding="utf-8",
    )
    request = CollectionRowsLoadRequest(
        path=path,
        storage_class=RootStorageClass.LOCAL,
    )

    first = CollectionRowsLoader().action(request=request)
    second = CollectionRowsLoader().action(request=request)

    assert type(first) is CollectionRowsLoadResult
    assert first == second
    assert first.request is request
    assert tuple(first.rows) == ("alpha2020", "beta2021")
    assert first.rows["alpha2020"].row_index == 1
    assert first.rows["beta2021"].row_index == 0
    assert len(first.rows.input_evidence) == 1
    assert first.rows.input_evidence[0].filename == "inputs/collection-rows.csv"
