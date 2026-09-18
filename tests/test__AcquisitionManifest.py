from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from projectkoios.references import (
    AcquisitionManifest,
    SearchRoot,
    create_acquisition_manifest,
    verify_acquisition_manifest,
)
from projectkoios.references.cli import main


def _rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "proposed_citekey": "example2026",
            "root_alias": "staging",
            "relative_path": "collection/example2026.pdf",
            "rights_status": "cc-by-4.0",
            "asset_status": "downloaded-private-local-staging",
            "identity_status": "unaccepted-candidate",
            "doi": "10.1234/example",
            "source_url": "https://example.test/article.pdf",
            "source_version": "published-version",
        },
    )


def _source(tmp_path: Path) -> tuple[Path, tuple[SearchRoot, ...]]:
    root = tmp_path / "private-source"
    pdf = root / "collection" / "example2026.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    return pdf, (SearchRoot("staging", root),)


def test__acquisition_manifest__retains_provenance_without_absolute_paths(
    tmp_path: Path,
) -> None:
    pdf, roots = _source(tmp_path)

    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    serialized = manifest.to_json()
    restored = AcquisitionManifest.from_json(serialized)
    verify_acquisition_manifest(restored, roots=roots)

    entry = restored.entries[0]
    assert entry.sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert entry.byte_size == pdf.stat().st_size
    assert entry.doi == "10.1234/example"
    assert str(tmp_path) not in serialized


def test__acquisition_manifest__detects_changed_source(
    tmp_path: Path,
) -> None:
    pdf, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    pdf.write_bytes(b"%PDF-1.4\nchanged")

    with pytest.raises(ValueError, match="source hash changed"):
        verify_acquisition_manifest(manifest, roots=roots)


def test__acquisition_manifest__rejects_traversal_and_duplicate_keys(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    unsafe = {**_rows()[0], "relative_path": "../example2026.pdf"}
    with pytest.raises(ValueError, match="traversal-free"):
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=(unsafe,),
            roots=roots,
        )

    duplicate = {**_rows()[0], "relative_path": "collection/other.pdf"}
    (roots[0].path / "collection" / "other.pdf").write_bytes(b"%PDF-1.4\nother")
    with pytest.raises(ValueError, match="duplicate citekeys"):
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=(_rows()[0], duplicate),
            roots=roots,
        )


def test__acquisition_cli__creates_and_verifies_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, roots = _source(tmp_path)
    metadata = tmp_path / "metadata.csv"
    with metadata.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(_rows()[0]))
        writer.writeheader()
        writer.writerows(_rows())
    output = tmp_path / "manifest.json"
    source_root = f"staging={roots[0].path}"

    assert (
        main(
            [
                "acquisition-create",
                str(metadata),
                str(output),
                "--source-id",
                "operator-recommendation-2026",
                "--source-root",
                source_root,
            ]
        )
        == 0
    )
    assert output.is_file()
    capsys.readouterr()

    assert (
        main(
            [
                "acquisition-verify",
                str(output),
                "--source-root",
                source_root,
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "schema_version": 1,
        "source_id": "operator-recommendation-2026",
        "verified": 1,
    }
