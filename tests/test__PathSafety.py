from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path

import pytest
from projectkoios.references import (
    AmbiguityEvaluation,
    AuthorizedRoot,
    PathSafetyError,
    validate_citekey,
    validate_relative_path,
)
from projectkoios.references.acquisition import create_acquisition_manifest
from projectkoios.references.assets import (
    AssetDiscoveryPlanner,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.collection_reconciliation import (
    CollectionManifest,
    CollectionReconciliationError,
    ReconciliationOutputs,
    publish_reconciliation,
    scan_managed_pdfs,
    scan_processing_evidence,
)
from projectkoios.references.models import ReferenceRecord
from projectkoios.references.validation import validate_reference_objects


def _record() -> ReferenceRecord:
    return ReferenceRecord(
        citekey="example2026",
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
    )


@pytest.mark.parametrize(
    "value",
    (
        "",
        "../private",
        "/absolute",
        "key/name",
        "key\\name",
        "1955example",
        "example.",
        "CON",
        "CON.txt",
        "éxample",
        "e\N{COMBINING ACUTE ACCENT}xample",
        "a" * 201,
    ),
)
def test__validate_citekey__rejects_nonportable_values(value: str) -> None:
    with pytest.raises(PathSafetyError, match="citekey"):
        validate_citekey(value)


def test__validate_relative_path__requires_normalized_portable_form() -> None:
    assert validate_relative_path("collection/example2026.pdf").as_posix() == (
        "collection/example2026.pdf"
    )
    assert validate_relative_path("café/example.pdf").as_posix() == (
        "café/example.pdf"
    )

    decomposed = unicodedata.normalize("NFD", "café/example.pdf")
    for value in (
        "../example.pdf",
        "/example.pdf",
        "collection\\example.pdf",
        "collection//example.pdf",
        "collection/./example.pdf",
        "collection/CON.pdf",
        "collection/example. ",
        decomposed,
    ):
        with pytest.raises(PathSafetyError):
            validate_relative_path(value)


def test__authorized_root__detects_root_replacement_before_read(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("original", encoding="utf-8")
    root = AuthorizedRoot.existing(root_path, label="fixture root")

    root_path.rename(tmp_path / "original-root")
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("replacement", encoding="utf-8")

    with pytest.raises(PathSafetyError, match="changed"):
        root.read_bytes("evidence.txt")


def test__authorized_root__rejects_leaf_and_directory_symlink_swaps(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("safe", encoding="utf-8")
    root = AuthorizedRoot.existing(root_path, label="fixture root")

    (root_path / "evidence.txt").unlink()
    (root_path / "evidence.txt").symlink_to(outside / "secret.txt")
    with pytest.raises(PathSafetyError):
        root.read_bytes("evidence.txt")

    (root_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathSafetyError):
        root.read_bytes("linked/secret.txt")


def test__asset_scan__rejects_symlink_file_and_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "example2026.pdf"
    external.write_bytes(b"%PDF-external")

    file_root = tmp_path / "file-root"
    file_root.mkdir()
    (file_root / "example2026.pdf").symlink_to(external)
    with pytest.raises(PathSafetyError, match="symlink"):
        AssetDiscoveryPlanner().scan(
            (_record(),),
            (SearchRoot("papers", file_root),),
        )

    directory_root = tmp_path / "directory-root"
    directory_root.mkdir()
    (directory_root / "linked").symlink_to(
        outside,
        target_is_directory=True,
    )
    with pytest.raises(PathSafetyError, match="symlink"):
        AssetDiscoveryPlanner().scan(
            (_record(),),
            (SearchRoot("papers", directory_root),),
        )


def test__materialize_asset__rechecks_source_and_destination_symlinks(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "example2026.pdf"
    content = b"%PDF-safe"
    source.write_bytes(content)
    roots = (SearchRoot("papers", source_root),)
    candidate = AssetDiscoveryPlanner().scan((_record(),), roots).candidates[0]

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(content)
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(PathSafetyError):
        materialize_asset(
            candidate,
            roots=roots,
            destination_directory=tmp_path / "assets-a",
        )

    source.unlink()
    source.write_bytes(content)
    destination = tmp_path / "assets-b"
    destination.mkdir()
    protected = tmp_path / "protected.pdf"
    protected.write_bytes(b"do not replace")
    (destination / "example2026.pdf").symlink_to(protected)
    with pytest.raises(PathSafetyError):
        materialize_asset(
            candidate,
            roots=roots,
            destination_directory=destination,
        )
    assert protected.read_bytes() == b"do not replace"


def test__acquisition__rejects_symlinked_source_component(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "example2026.pdf").write_bytes(b"%PDF-external")
    root = tmp_path / "source"
    root.mkdir()
    (root / "collection").symlink_to(outside, target_is_directory=True)
    rows = (
        {
            "proposed_citekey": "example2026",
            "root_alias": "staging",
            "relative_path": "collection/example2026.pdf",
            "rights_status": "unreviewed",
            "asset_status": "candidate",
            "identity_status": "unaccepted-candidate",
        },
    )

    with pytest.raises(PathSafetyError):
        create_acquisition_manifest(
            source_id="fixture",
            rows=rows,
            roots=(SearchRoot("staging", root),),
        )


def test__processing_lookup__rejects_traversal_and_symlink_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ingestion"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "extraction.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CollectionReconciliationError, match="unsafe"):
        scan_processing_evidence(root, citekeys=("../outside",))

    (root / "example2026").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CollectionReconciliationError, match="unsafe"):
        scan_processing_evidence(root, citekeys=("example2026",))


def test__managed_pdf_and_object_validation__reject_symlinks(
    tmp_path: Path,
) -> None:
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-external")
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "example2026.pdf").symlink_to(outside_pdf)

    with pytest.raises(CollectionReconciliationError, match="symlink"):
        scan_managed_pdfs(pdfs)

    notes = tmp_path / "notes"
    notes.mkdir()
    outside_note = tmp_path / "outside.md"
    outside_note.write_text("citekey: example2026\n", encoding="utf-8")
    (notes / "example2026.md").symlink_to(outside_note)
    with pytest.raises(PathSafetyError, match="symlink"):
        validate_reference_objects(
            (_record(),),
            notes_directory=notes,
            pdf_directory=pdfs,
        )


def test__publication__does_not_follow_output_directory_symlink(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "outputs"
    parent.mkdir()
    destination = parent / "fixture"
    destination.symlink_to(outside, target_is_directory=True)
    manifest = CollectionManifest(
        schema_version=1,
        processor_version="fixture",
        collection_id="fixture",
        source_revision="revision",
        bibliography_sha256=hashlib.sha256(b"fixture").hexdigest(),
        coverage_observation_id=None,
        coverage_state=None,
        ambiguity_evaluation=AmbiguityEvaluation.NOT_EVALUATED,
        coverage=(),
        references=(),
        extra_pdfs=(),
        counts={},
        manifest_id="collection-manifest:sha256:" + "0" * 64,
    )
    outputs = ReconciliationOutputs(
        manifest=manifest,
        citation_closure=None,
        files=(("collection-manifest.json", b"{}\n"),),
    )

    with pytest.raises(CollectionReconciliationError, match="symlink"):
        publish_reconciliation(outputs, output_directory=destination)
    assert tuple(outside.iterdir()) == ()


def test__authorized_write__is_create_only_and_does_not_follow_symlink(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(root_path, label="write root")
    written = root.write_bytes("result.txt", b"first", replace=False)
    assert written.read_bytes() == b"first"
    with pytest.raises(FileExistsError):
        root.write_bytes("result.txt", b"second", replace=False)

    written.unlink()
    protected = tmp_path / "protected.txt"
    protected.write_bytes(b"protected")
    os.symlink(protected, written)
    with pytest.raises(PathSafetyError):
        root.write_bytes("result.txt", b"replacement", replace=True)
    assert protected.read_bytes() == b"protected"
