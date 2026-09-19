from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references import (
    ACQUISITION_CONTRACT_STATUS,
    ACQUISITION_IO_LIMITS,
    ACQUISITION_MANIFEST_SCHEMA_VERSION,
    AccessObservation,
    AcquisitionManifest,
    AcquisitionObservation,
    AcquisitionPublicationError,
    PathSafetyError,
    ReferenceIOLimitError,
    RightsObservation,
    RootStorageClass,
    SearchRoot,
    create_acquisition_manifest,
    publish_acquisition_manifest,
    verify_acquisition_manifest,
)
from projectkoios.references.cli import main


def _rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "proposed_citekey": "example2026",
            "root_alias": "staging",
            "relative_path": "collection/example2026.pdf",
            "acquisition_status": "operator-asserted-lawfully-held",
            "access_status": "private-local-bytes-observed",
            "rights_status": "cc-by-4.0-operator-asserted",
            "identity_status": "unaccepted-candidate",
            "doi": "10.1234/example",
            "source_url": "https://example.test/article.pdf",
            "source_version": "published-version",
        },
    )


def _manifest_identity(
    manifest: AcquisitionManifest,
    *,
    effective_limits: object,
    effective_limits_id: str,
) -> str:
    return AcquisitionManifest.identity_for(
        schema_version=manifest.schema_version,
        artifact_kind=manifest.artifact_kind,
        contract_id=manifest.contract_id,
        contract_version=manifest.contract_version,
        contract_status=manifest.contract_status,
        generator_name=manifest.generator_name,
        generator_version=manifest.generator_version,
        source_id=manifest.source_id,
        normalized_input_id=manifest.normalized_input_id,
        coverage_status=manifest.coverage_status,
        effective_limits=effective_limits,
        effective_limits_id=effective_limits_id,
        root_preflights=manifest.root_preflights,
        entries=manifest.entries,
    )


def _replace_path_during_first_read(
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
) -> None:
    original_fdopen = os.fdopen
    original_fstat = os.fstat
    replaced = False
    opened_file_metadata: os.stat_result | None = None

    class ReplacingReader:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self) -> ReplacingReader:
            self.stream.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            return self.stream.__exit__(*args)  # type: ignore[attr-defined]

        def read(self, *args: object) -> bytes:
            nonlocal replaced
            content = self.stream.read(*args)  # type: ignore[attr-defined]
            if not replaced:
                replaced = True
                path.rename(path.with_name(path.name + ".opened"))
                path.write_bytes(b"%PDF-replacement")
            return content

    def replacing_fdopen(*args: object, **kwargs: object) -> object:
        stream = original_fdopen(*args, **kwargs)  # type: ignore[arg-type]
        return ReplacingReader(stream)

    def stable_open_file_fstat(descriptor: int) -> os.stat_result:
        nonlocal opened_file_metadata
        metadata = original_fstat(descriptor)
        if stat.S_ISREG(metadata.st_mode):
            if opened_file_metadata is None:
                opened_file_metadata = metadata
            return opened_file_metadata
        return metadata

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.fdopen",
        replacing_fdopen,
    )
    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.fstat",
        stable_open_file_fstat,
    )


def _source(tmp_path: Path) -> tuple[Path, tuple[SearchRoot, ...]]:
    root = tmp_path / "private-source"
    pdf = root / "collection" / "example2026.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    return pdf, (SearchRoot("staging", root, RootStorageClass.LOCAL),)


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
    assert entry.identity_status == "unaccepted-candidate"
    assert entry.citekey_status == "proposed-noncanonical"
    assert entry.manuscript_status == "not-assessed"
    assert entry.acquisition == AcquisitionObservation(
        "operator-asserted-lawfully-held", "operator-assertion"
    )
    assert entry.access == AccessObservation(
        "private-local-bytes-observed", "operator-assertion"
    )
    assert entry.rights == RightsObservation(
        "cc-by-4.0-operator-asserted", "operator-assertion"
    )
    assert restored.contract_status == ACQUISITION_CONTRACT_STATUS
    assert restored.manifest_id.startswith("acquisition-manifest:sha256:")
    assert restored.normalized_input_id.startswith("acquisition-input:sha256:")
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

    authority_claim = {
        **_rows()[0],
        "identity_status": "accepted-reference",
    }
    with pytest.raises(ValueError, match="unsupported identity_status"):
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=(authority_claim,),
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

    with pytest.raises(ValueError, match="path-free"):
        create_acquisition_manifest(
            source_id=str(tmp_path),
            rows=_rows(),
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
    source_root = f"local:staging={roots[0].path}"

    assert (
        main(
            [
                "acquisition-create",
                str(metadata),
                str(output),
                "--source-id",
                "operator-recommendation-2026",
                "--metadata-storage-class",
                "local",
                "--output-storage-class",
                "local",
                "--source-root",
                source_root,
            ]
        )
        == 0
    )
    assert output.is_file()
    creation_report = json.loads(capsys.readouterr().out)
    assert creation_report["status"] == "created"
    assert creation_report["entries"] == 1
    assert "output" not in creation_report
    assert str(tmp_path) not in json.dumps(creation_report)

    assert (
        main(
            [
                "acquisition-verify",
                str(output),
                "--manifest-storage-class",
                "local",
                "--source-root",
                source_root,
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == ACQUISITION_MANIFEST_SCHEMA_VERSION
    assert report["source_id"] == "operator-recommendation-2026"
    assert report["verified"] == 1
    assert report["coverage_status"] == "complete"
    assert report["contract_status"] == "proposed"
    assert report["manifest_id"].startswith("acquisition-manifest:sha256:")
    assert report["effective_limits_id"].startswith(
        "reference-io-limits:sha256:"
    )


@pytest.mark.parametrize(
    ("csv_text", "message"),
    (
        (
            "proposed_citekey,root_alias,relative_path,access_status,"
            "rights_status,rights_status,identity_status\n"
            "example2026,staging,collection/example2026.pdf,available,"
            "asserted,duplicate,unaccepted-candidate\n",
            "duplicate headers",
        ),
        (
            "proposed_citekey,root_alias,relative_path,access_status,"
            "rights_status,identity_status\n"
            "example2026,staging,collection/example2026.pdf,available,"
            "asserted,unaccepted-candidate,surplus\n",
            "surplus fields",
        ),
    ),
)
def test__acquisition_cli__rejects_noncanonical_csv_shape(
    tmp_path: Path,
    csv_text: str,
    message: str,
) -> None:
    _, roots = _source(tmp_path)
    metadata = tmp_path / "metadata.csv"
    metadata.write_text(csv_text, encoding="utf-8")
    output = tmp_path / "manifest.json"

    with pytest.raises(ValueError, match=message):
        main(
            [
                "acquisition-create",
                str(metadata),
                str(output),
                "--source-id",
                "operator-recommendation-2026",
                "--metadata-storage-class",
                "local",
                "--output-storage-class",
                "local",
                "--source-root",
                f"local:staging={roots[0].path}",
            ]
        )
    assert not output.exists()


def test__acquisition_observations__enforce_basis_semantics(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    with pytest.raises(ValueError, match="not-assessed status"):
        AcquisitionObservation("operator-asserted", "explicitly-not-assessed")
    with pytest.raises(ValueError, match="operator assertion"):
        AccessObservation("not-assessed", "explicitly-not-assessed")
    with pytest.raises(ValueError, match="operator assertion"):
        RightsObservation("not-assessed", "explicitly-not-assessed")

    rows = (
        {
            key: value
            for key, value in _rows()[0].items()
            if key != "acquisition_status"
        },
    )
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=rows,
        roots=roots,
    )
    assert manifest.entries[0].acquisition == AcquisitionObservation(
        "not-assessed", "explicitly-not-assessed"
    )

    payload = json.loads(manifest.to_json())
    payload["entries"][0]["rights_observation"]["basis"] = (
        "explicitly-not-assessed"
    )
    with pytest.raises(ValueError, match="operator assertion"):
        AcquisitionManifest.from_json(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )


def test__acquisition_source_url__treats_path_as_opaque_public_input(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    opaque_path = (
        {
            **_rows()[0],
            "source_url": "https://example.test/opaque/segment/document.pdf",
        },
    )
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=opaque_path,
        roots=roots,
    )
    assert manifest.entries[0].source_url == opaque_path[0]["source_url"]

    malformed_urls = (
        "https://example.test/document.pdf?signature=x",
        "https://:443/document.pdf",
        "https://example.test:not-a-port/document.pdf",
    )
    for source_url in malformed_urls:
        with pytest.raises(ValueError, match="without credentials, query"):
            create_acquisition_manifest(
                source_id="operator-recommendation-2026",
                rows=({**_rows()[0], "source_url": source_url},),
                roots=roots,
            )


def test__acquisition_manifest__identity_binds_normalized_input_and_source(
    tmp_path: Path,
) -> None:
    pdf, roots = _source(tmp_path)
    first = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    replay = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    assert replay.to_json() == first.to_json()
    assert replay.manifest_id == first.manifest_id
    assert replay.normalized_input_id == first.normalized_input_id

    changed_rows = ({**_rows()[0], "rights_status": "rights-not-assessed"},)
    changed_input = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=changed_rows,
        roots=roots,
    )
    assert changed_input.normalized_input_id != first.normalized_input_id
    assert changed_input.manifest_id != first.manifest_id

    pdf.write_bytes(b"%PDF-1.4\nchanged-but-same-metadata")
    changed_source = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    assert changed_source.normalized_input_id == first.normalized_input_id
    assert changed_source.manifest_id != first.manifest_id


def test__acquisition_manifest__rejects_tamper_and_projects_typed_evidence(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    projection = manifest.projections()[0]
    assert projection.manifest_id == manifest.manifest_id
    assert projection.source_content_id == (
        "blob:sha256:" + manifest.entries[0].sha256
    )
    assert projection.identity_status == "unaccepted-candidate"
    assert projection.citekey_status == "proposed-noncanonical"
    assert projection.manuscript_status == "not-assessed"
    assert isinstance(projection.acquisition, AcquisitionObservation)
    assert isinstance(projection.access, AccessObservation)
    assert isinstance(projection.rights, RightsObservation)

    payload = json.loads(manifest.to_json())
    payload["entries"][0]["rights_observation"]["status"] = "changed"
    with pytest.raises(ValueError, match="identity"):
        AcquisitionManifest.from_json(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
    with pytest.raises(ValueError, match="canonical"):
        AcquisitionManifest.from_json(manifest.to_json() + "\n")


def test__acquisition_publication__creates_or_accepts_only_identical_replay(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    output = tmp_path / "published" / "manifest.json"

    created = publish_acquisition_manifest(
        manifest,
        output_path=output,
        output_storage_class=RootStorageClass.LOCAL,
    )
    original = output.read_bytes()
    assert created.status == "created"
    unchanged = publish_acquisition_manifest(
        manifest,
        output_path=output,
        output_storage_class=RootStorageClass.LOCAL,
    )
    assert unchanged.status == "unchanged"
    assert output.read_bytes() == original

    output.write_bytes(original[:-1])
    with pytest.raises(AcquisitionPublicationError, match="partial repair"):
        publish_acquisition_manifest(
            manifest,
            output_path=output,
            output_storage_class=RootStorageClass.LOCAL,
        )
    assert output.read_bytes() == original[:-1]


def test__acquisition_publication__rejects_symlink_and_oversized_existing(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    target = output_parent / "target.json"
    target.write_bytes(manifest.to_json().encode("utf-8"))
    symlink = output_parent / "manifest.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        publish_acquisition_manifest(
            manifest,
            output_path=symlink,
            output_storage_class=RootStorageClass.LOCAL,
        )

    symlink.unlink()
    maximum = manifest.effective_limits.max_json_bytes
    assert maximum is not None
    with symlink.open("wb") as stream:
        stream.truncate(maximum + 1)
    with pytest.raises(ReferenceIOLimitError) as caught:
        publish_acquisition_manifest(
            manifest,
            output_path=symlink,
            output_storage_class=RootStorageClass.LOCAL,
        )
    assert caught.value.coverage_status == "incomplete"
    assert caught.value.limit_name == "max_file_bytes"


def test__acquisition_verification__uses_recorded_streaming_limits(
    tmp_path: Path,
) -> None:
    pdf, roots = _source(tmp_path)
    tight = replace(ACQUISITION_IO_LIMITS, max_file_bytes=20)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
        limits=tight,
    )
    pdf.write_bytes(b"%PDF-" + b"x" * 20)

    with pytest.raises(ReferenceIOLimitError) as caught:
        verify_acquisition_manifest(manifest, roots=roots)
    assert caught.value.limit_name == "max_file_bytes"
    assert caught.value.coverage_status == "incomplete"


def test__acquisition_limits__bound_file_count_and_aggregate_before_overread(
    tmp_path: Path,
) -> None:
    pdf, roots = _source(tmp_path)
    second = pdf.with_name("other2026.pdf")
    second.write_bytes(b"%PDF-1.4\nother")
    second_row = {
        **_rows()[0],
        "proposed_citekey": "other2026",
        "relative_path": "collection/other2026.pdf",
    }
    file_limited = replace(ACQUISITION_IO_LIMITS, max_files=1)
    duplicate_source = {
        **_rows()[0],
        "proposed_citekey": "duplicate2026",
    }
    with pytest.raises(ValueError, match="duplicates an earlier source"):
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=(_rows()[0], duplicate_source),
            roots=roots,
            limits=file_limited,
        )

    extra_root_path = tmp_path / "extra-root"
    extra_root_path.mkdir()
    extra_roots = (
        *roots,
        SearchRoot("unused", extra_root_path, RootStorageClass.LOCAL),
    )
    extra_root_manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=extra_roots,
        limits=file_limited,
    )
    assert tuple(
        item.root_alias for item in extra_root_manifest.root_preflights
    ) == ("staging", "unused")

    with pytest.raises(ReferenceIOLimitError) as file_failure:
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=(_rows()[0], second_row),
            roots=roots,
            limits=file_limited,
        )
    assert file_failure.value.limit_name == "max_files"

    total_limited = replace(
        ACQUISITION_IO_LIMITS,
        max_total_bytes=pdf.stat().st_size - 1,
    )
    with pytest.raises(ReferenceIOLimitError) as total_failure:
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=_rows(),
            roots=roots,
            limits=total_limited,
        )
    assert total_failure.value.limit_name == "max_total_bytes"
    assert total_failure.value.observed == pdf.stat().st_size

    recorded_total = replace(
        ACQUISITION_IO_LIMITS,
        max_total_bytes=pdf.stat().st_size,
    )
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
        limits=recorded_total,
    )
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(ReferenceIOLimitError) as verify_failure:
        verify_acquisition_manifest(manifest, roots=roots)
    assert verify_failure.value.limit_name == "max_total_bytes"


def test__acquisition_manifest__rejects_reidentified_limit_contradictions(
    tmp_path: Path,
) -> None:
    _, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    file_limit = manifest.entries[0].byte_size - 1
    tightened = replace(
        manifest.effective_limits,
        max_file_bytes=file_limit,
    )
    tightened_id = tightened.evidence_id
    reidentified = _manifest_identity(
        manifest,
        effective_limits=tightened,
        effective_limits_id=tightened_id,
    )
    with pytest.raises(ReferenceIOLimitError) as file_failure:
        replace(
            manifest,
            effective_limits=tightened,
            effective_limits_id=tightened_id,
            manifest_id=reidentified,
        )
    assert file_failure.value.limit_name == "max_file_bytes"

    json_limited = replace(
        manifest.effective_limits,
        max_json_bytes=100,
    )
    json_limited_id = json_limited.evidence_id
    json_reidentified = _manifest_identity(
        manifest,
        effective_limits=json_limited,
        effective_limits_id=json_limited_id,
    )
    with pytest.raises(ReferenceIOLimitError) as json_failure:
        replace(
            manifest,
            effective_limits=json_limited,
            effective_limits_id=json_limited_id,
            manifest_id=json_reidentified,
        )
    assert json_failure.value.limit_name == "max_json_bytes"


def test__acquisition_source__rejects_leaf_replacement_during_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf, roots = _source(tmp_path)
    _replace_path_during_first_read(monkeypatch, pdf)

    with pytest.raises(PathSafetyError, match="changed|replaced"):
        create_acquisition_manifest(
            source_id="operator-recommendation-2026",
            rows=_rows(),
            roots=roots,
        )


def test__acquisition_replay__rejects_output_replacement_during_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots = _source(tmp_path)
    manifest = create_acquisition_manifest(
        source_id="operator-recommendation-2026",
        rows=_rows(),
        roots=roots,
    )
    output = tmp_path / "output" / "manifest.json"
    publish_acquisition_manifest(
        manifest,
        output_path=output,
        output_storage_class=RootStorageClass.LOCAL,
    )
    _replace_path_during_first_read(monkeypatch, output)

    with pytest.raises(PathSafetyError, match="changed|replaced"):
        publish_acquisition_manifest(
            manifest,
            output_path=output,
            output_storage_class=RootStorageClass.LOCAL,
        )
