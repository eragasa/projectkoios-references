from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references.citation_closure import CitationScanMode
from projectkoios.references.citation_closure import (
    build_citation_closure as _build_citation_closure,
)
from projectkoios.references.collections.reconciliation.errors import (
    CollectionReconciliationError,
    IncompleteReconciliationPublicationError,
)
from projectkoios.references.collections.reconciliation.loading import (
    CollectionRowsLoader,
    CollectionRowsLoadRequest,
    ManagedPdfScanner,
    ManagedPdfScanRequest,
)
from projectkoios.references.collections.reconciliation.manifest import (
    ReconciliationOutputs,
)
from projectkoios.references.collections.reconciliation.publication import (
    ReconciliationPackageVerificationRequest,
    ReconciliationPackageVerifier,
    ReconciliationPublicationRequest,
    ReconciliationPublisher,
)
from projectkoios.references.collections.reconciliation.reconciliation import (
    CollectionReconciler,
    CollectionReconciliationRequest,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)
from projectkoios.references.path_safety import AuthorizedRoot, RootStorageClass


def build_citation_closure(*args: object, **kwargs: object):
    kwargs["storage_class"] = RootStorageClass.LOCAL
    kwargs["mode"] = CitationScanMode.ALL_FILES_OBSERVATION
    kwargs["entrypoint"] = None
    return _build_citation_closure(*args, **kwargs)


def _write_collection_rows(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "citekey",
                "source_bibliographies",
                "bibliographic_status",
                "reading_status",
            ),
            lineterminator="\n",
        )
        writer.writeheader()
        for citekey in ("alpha2020", "beta2021", "manual2022"):
            writer.writerow(
                {
                    "citekey": citekey,
                    "source_bibliographies": "manuscript/references.bib",
                    "bibliographic_status": "imported-unverified",
                    "reading_status": "unread-or-unknown",
                }
            )


def _candidate(**values: object) -> ReferenceCandidate:
    return ReferenceCandidate.create(
        **values,
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def _records() -> tuple[ReferenceCandidate, ...]:
    return (
        _candidate(
            proposed_citekey="beta2021",
            entry_type="article",
            title="Beta",
            authors=("B. Author",),
            year="2021",
            doi="10.1000/beta",
        ),
        _candidate(
            proposed_citekey="manual2022",
            entry_type="manual",
            title="Manual",
            authors=(),
            year="2022",
        ),
        _candidate(
            proposed_citekey="alpha2020",
            entry_type="article",
            title="Alpha",
            authors=("A. Author",),
            year="2020",
            doi="10.1000/alpha",
        ),
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, bytes]:
    corpus = tmp_path / "corpus.csv"
    _write_collection_rows(corpus)
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    pdf_bytes = b"%PDF-1.4\nfixture\n%%EOF\n"
    (pdfs / "alpha2020.pdf").write_bytes(pdf_bytes)
    (pdfs / "extra2023.pdf").write_bytes(pdf_bytes)
    discovery = tmp_path / "source-discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "matches": [
                    {
                        "citekey": "alpha2020",
                        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                        "match_basis": "fixture identity evidence",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(
        "\n        \\cite{alpha2020,beta2021}\n"
        "        % \\cite{commentedOut}\n"
        "        Literal percent \\% then \\textcite{undefined2024}.\n"
        "        \\newcommand{\\wrappedcite}[1]{\\cite{#1}}\n"
        "        \\newcommand{\\nestedwrappedcite}[1]{\\cite{##1}}\n"
        "        ",
        encoding="utf-8",
    )
    return (corpus, pdfs, discovery, pdf_bytes)


def _publication_outputs(tmp_path: Path) -> ReconciliationOutputs:
    corpus, pdfs, discovery, pdf_bytes = _inputs(tmp_path)
    del pdf_bytes
    records = _records()
    return (
        CollectionReconciler()
        .action(
            request=CollectionReconciliationRequest(
                records=records,
                bibliography_bytes=b"fixture bibliography",
                collection_id="fixture",
                source_revision="abc123",
                collection_rows=CollectionRowsLoader()
                .action(
                    request=CollectionRowsLoadRequest(
                        path=corpus, storage_class=RootStorageClass.LOCAL
                    )
                )
                .rows,
                managed_pdfs=ManagedPdfScanner()
                .action(
                    request=ManagedPdfScanRequest(
                        directory=pdfs,
                        source_discovery=discovery,
                        storage_class=RootStorageClass.LOCAL,
                        source_discovery_storage_class=RootStorageClass.LOCAL,
                    )
                )
                .scan,
                citation_closure=build_citation_closure(
                    tmp_path / "manuscript",
                    bibliography_keys=tuple(
                        record.proposed_citekey for record in records
                    ),
                    source_revision="abc123",
                ),
            )
        )
        .outputs
    )


def test__ReconciliationPublisher__rejects_inconsistent_output_objects(
    tmp_path: Path,
) -> None:
    outputs = _publication_outputs(tmp_path)
    with pytest.raises(ValueError, match="collection manifest differs"):
        replace(
            outputs,
            manifest=replace(outputs.manifest, collection_id="other"),
        )
    with pytest.raises(ValueError, match="sorted, and unique"):
        replace(outputs, files=outputs.files + (outputs.files[0],))
    with pytest.raises(ValueError, match="sorted, and unique"):
        replace(outputs, files=tuple(reversed(outputs.files)))

    forged = object.__new__(ReconciliationOutputs)
    for name in (
        "manifest",
        "citation_closure",
        "package_manifest",
    ):
        object.__setattr__(forged, name, getattr(outputs, name))
    object.__setattr__(forged, "files", outputs.files + (outputs.files[0],))
    with pytest.raises(
        CollectionReconciliationError, match="sorted, and unique"
    ):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=forged,
                output_directory=tmp_path / "forged",
                output_storage_class=RootStorageClass.LOCAL,
            )
        )


def test__ReconciliationPublisher__is_immutable_and_replayable(
    tmp_path: Path,
) -> None:
    outputs = _publication_outputs(tmp_path)
    destination = tmp_path / "output" / "fixture"
    created = (
        ReconciliationPublisher()
        .action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
        .publication
    )
    unchanged = (
        ReconciliationPublisher()
        .action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
        .publication
    )
    assert created.status == "created"
    assert unchanged.status == "unchanged"
    assert created.package_id == unchanged.package_id
    assert created.package_id == outputs.package_manifest.package_id
    (destination / "missing-pdfs.csv").write_text(
        "different\n", encoding="utf-8"
    )
    with pytest.raises(CollectionReconciliationError, match="differs"):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )


def test__ReconciliationPublisher__writes_package_manifest_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = _publication_outputs(tmp_path)
    destination = tmp_path / "output" / "fixture"
    writes: list[str] = []
    original_write = AuthorizedRoot.write_bytes

    def tracked_write(
        self: AuthorizedRoot, relative: str, content: bytes, *, replace: bool
    ) -> Path:
        writes.append(str(relative))
        return original_write(self, relative, content, replace=replace)

    monkeypatch.setattr(AuthorizedRoot, "write_bytes", tracked_write)
    result = (
        ReconciliationPublisher()
        .action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
        .publication
    )
    assert result.status == "created"
    assert writes[-1] == "package-manifest.json"
    assert set(writes) == {name for name, _content in outputs.files}


def test__ReconciliationPublisher__mkdir_race_never_mutates_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = _publication_outputs(tmp_path)
    destination = tmp_path / "output" / "fixture"
    original_create = AuthorizedRoot.create_directory
    injected = False

    def raced_create(self: AuthorizedRoot, relative: str) -> AuthorizedRoot:
        nonlocal injected
        if not injected and str(relative) == "fixture":
            injected = True
            raced = self.child_path(relative)
            raced.mkdir()
            (raced / "winner-owned.txt").write_text("winner", encoding="utf-8")
        return original_create(self, relative)

    monkeypatch.setattr(AuthorizedRoot, "create_directory", raced_create)
    with pytest.raises(
        IncompleteReconciliationPublicationError, match="completion manifest"
    ):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
    assert injected
    assert sorted(path.name for path in destination.iterdir()) == [
        "winner-owned.txt"
    ]
    assert (destination / "winner-owned.txt").read_text(
        encoding="utf-8"
    ) == "winner"


def test__ReconciliationPublisher__write_failure_leaves_incomplete_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = _publication_outputs(tmp_path)
    destination = tmp_path / "output" / "fixture"
    original_write = AuthorizedRoot.write_bytes
    failed = False

    def fail_payload_once(
        self: AuthorizedRoot, relative: str, content: bytes, *, replace: bool
    ) -> Path:
        nonlocal failed
        if not failed and str(relative) != "package-manifest.json":
            failed = True
            raise OSError("synthetic payload write failure")
        return original_write(self, relative, content, replace=replace)

    monkeypatch.setattr(AuthorizedRoot, "write_bytes", fail_payload_once)
    with pytest.raises(IncompleteReconciliationPublicationError) as caught:
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
    assert caught.value.code == "reconciliation-publication-incomplete"
    assert destination.is_dir()
    assert not (destination / "package-manifest.json").exists()


def test__ReconciliationPublisher__extra_file_fails_exact_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = _publication_outputs(tmp_path)
    destination = tmp_path / "output" / "fixture"
    original_write = AuthorizedRoot.write_bytes

    def inject_extra_before_final_payload(
        self: AuthorizedRoot, relative: str, content: bytes, *, replace: bool
    ) -> Path:
        if str(relative) == "package-manifest.json":
            self.child_path("unexpected.txt").write_text(
                "raced", encoding="utf-8"
            )
        return original_write(self, relative, content, replace=replace)

    monkeypatch.setattr(
        AuthorizedRoot, "write_bytes", inject_extra_before_final_payload
    )
    with pytest.raises(
        IncompleteReconciliationPublicationError,
        match="incomplete or unexpected",
    ):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
    assert (destination / "package-manifest.json").is_file()
    assert (destination / "unexpected.txt").read_text(
        encoding="utf-8"
    ) == "raced"
    with pytest.raises(
        CollectionReconciliationError,
        match="incomplete or unexpected",
    ):
        ReconciliationPackageVerifier().action(
            request=ReconciliationPackageVerificationRequest(
                directory=destination,
                storage_class=RootStorageClass.LOCAL,
            )
        )
