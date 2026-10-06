from __future__ import annotations

import json
from pathlib import Path

import pytest
from projectkoios.references.collections.reconciliation.errors import (
    CollectionReconciliationError,
    IncompleteReconciliationPublicationError,
)
from projectkoios.references.collections.reconciliation.operation import (
    COLLECTION_RECONCILIATION_OPERATION_ACTION_ID,
    CollectionReconciliationOperation,
    CollectionReconciliationOperationRequest,
    CollectionReconciliationOperationResult,
)
from projectkoios.references.path_safety import RootStorageClass

from scripts.koios_ref import main


def _inputs(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir()
    bibliography = root / "references.bib"
    bibliography.write_text(
        "@article{example2026, title={Example}, year={2026}}\n",
        encoding="utf-8",
    )
    corpus = root / "corpus.csv"
    corpus.write_text(
        "citekey,source_bibliographies,bibliographic_status,reading_status\n"
        "example2026,references.bib,imported-unverified,unread-or-unknown\n",
        encoding="utf-8",
    )
    pdfs = root / "pdfs"
    pdfs.mkdir()
    return bibliography, corpus, pdfs


def _request(
    *,
    bibliography: Path,
    corpus: Path,
    pdfs: Path,
    output: Path,
) -> CollectionReconciliationOperationRequest:
    return CollectionReconciliationOperationRequest(
        bibliography=bibliography,
        bibliography_storage_class=RootStorageClass.LOCAL,
        corpus=corpus,
        corpus_storage_class=RootStorageClass.LOCAL,
        pdfs=pdfs,
        pdf_storage_class=RootStorageClass.LOCAL,
        output_directory=output,
        output_storage_class=RootStorageClass.LOCAL,
        collection_id="fixture",
        source_revision="asserted-fixture-revision",
    )


def _published_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
    }


def test__operation__owns_complete_reconciliation_and_exact_replay(
    tmp_path: Path,
) -> None:
    bibliography, corpus, pdfs = _inputs(tmp_path / "inputs")
    output_a = tmp_path / "output-a"
    request_a = _request(
        bibliography=bibliography,
        corpus=corpus,
        pdfs=pdfs,
        output=output_a,
    )
    operation = CollectionReconciliationOperation()

    first = operation.action(request=request_a)
    replayed = operation.action(request=request_a)
    output_b = tmp_path / "output-b"
    rebuilt = operation.action(
        request=_request(
            bibliography=bibliography,
            corpus=corpus,
            pdfs=pdfs,
            output=output_b,
        )
    )

    assert type(first) is CollectionReconciliationOperationResult
    assert operation.action_id == COLLECTION_RECONCILIATION_OPERATION_ACTION_ID
    assert first.publication.publication.status == "created"
    assert replayed.publication.publication.status == "unchanged"
    assert rebuilt.publication.publication.status == "created"
    assert first.reconciliation.outputs == replayed.reconciliation.outputs
    assert first.reconciliation.outputs == rebuilt.reconciliation.outputs
    assert first.publication.publication.package_id == (
        rebuilt.publication.publication.package_id
    )
    assert _published_bytes(output_a) == _published_bytes(output_b)
    for published_file in output_a.iterdir():
        assert str(tmp_path).encode("utf-8") not in published_file.read_bytes()


def test__cli__is_an_equivalent_adapter_for_the_owner_operation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bibliography, corpus, pdfs = _inputs(tmp_path / "inputs")
    owner_output = tmp_path / "owner-output"
    cli_output = tmp_path / "cli-output"
    owner_result = CollectionReconciliationOperation().action(
        request=_request(
            bibliography=bibliography,
            corpus=corpus,
            pdfs=pdfs,
            output=owner_output,
        )
    )

    assert (
        main(
            [
                "collection-reconcile",
                str(bibliography),
                str(corpus),
                str(pdfs),
                str(cli_output),
                "--collection-id",
                "fixture",
                "--source-revision",
                "asserted-fixture-revision",
                "--bibliography-storage-class",
                "local",
                "--corpus-storage-class",
                "local",
                "--pdf-storage-class",
                "local",
                "--output-storage-class",
                "local",
            ]
        )
        == 0
    )

    report = json.loads(capsys.readouterr().out)
    assert report["package_id"] == (
        owner_result.publication.publication.package_id
    )
    assert report["status"] == "created"
    assert _published_bytes(owner_output) == _published_bytes(cli_output)


def test__operation__rejects_incomplete_capabilities_before_effects(
    tmp_path: Path,
) -> None:
    bibliography, corpus, pdfs = _inputs(tmp_path / "inputs")
    output = tmp_path / "output"

    with pytest.raises(
        ValueError,
        match="coverage_observation path and storage class",
    ):
        CollectionReconciliationOperationRequest(
            bibliography=bibliography,
            bibliography_storage_class=RootStorageClass.LOCAL,
            corpus=corpus,
            corpus_storage_class=RootStorageClass.LOCAL,
            pdfs=pdfs,
            pdf_storage_class=RootStorageClass.LOCAL,
            output_directory=output,
            output_storage_class=RootStorageClass.LOCAL,
            collection_id="fixture",
            source_revision="asserted-fixture-revision",
            coverage_observation=tmp_path / "coverage.json",
        )

    assert not output.exists()


def test__operation__does_not_publish_after_invalid_input(
    tmp_path: Path,
) -> None:
    bibliography, corpus, pdfs = _inputs(tmp_path / "inputs")
    bibliography.write_text("not bibtex\n", encoding="utf-8")
    output = tmp_path / "output"

    with pytest.raises(CollectionReconciliationError):
        CollectionReconciliationOperation().action(
            request=_request(
                bibliography=bibliography,
                corpus=corpus,
                pdfs=pdfs,
                output=output,
            )
        )

    assert not output.exists()


def test__operation__refuses_to_repair_incomplete_publication(
    tmp_path: Path,
) -> None:
    bibliography, corpus, pdfs = _inputs(tmp_path / "inputs")
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "operator-evidence.txt"
    sentinel.write_text("do not replace\n", encoding="utf-8")

    with pytest.raises(IncompleteReconciliationPublicationError):
        CollectionReconciliationOperation().action(
            request=_request(
                bibliography=bibliography,
                corpus=corpus,
                pdfs=pdfs,
                output=output,
            )
        )

    assert sentinel.read_text(encoding="utf-8") == "do not replace\n"
    assert tuple(path.name for path in output.iterdir()) == (
        "operator-evidence.txt",
    )
