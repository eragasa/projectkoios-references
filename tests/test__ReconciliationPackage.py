from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from pathlib import Path

import pytest
from projectkoios.references.collection_reconciliation import (
    CollectionReconciliationError,
    build_citation_closure,
    load_collection_rows,
    parse_reconciliation_package,
    publish_reconciliation,
    reconcile_collection,
    replay_reconciliation,
    scan_managed_pdfs,
    scan_processing_evidence,
    verify_reconciliation_package,
)
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.models import ReferenceRecord
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    FrozenCounts,
)

_ASSERTED_REVISION = "caller-asserted-revision"


def _record() -> ReferenceRecord:
    return ReferenceRecord(
        citekey="example2026",
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
    )


def _prepare_inputs(root: Path) -> dict[str, Path]:
    root.mkdir()
    bibliography = root / "references.bib"
    bibliography.write_text(
        "@article{example2026, title={Example}, year={2026}}\n",
        encoding="utf-8",
    )
    corpus = root / "corpus.csv"
    with corpus.open("w", encoding="utf-8", newline="") as stream:
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
        writer.writerow(
            {
                "citekey": "example2026",
                "source_bibliographies": "references.bib",
                "bibliographic_status": "imported-unverified",
                "reading_status": "unread-or-unknown",
            }
        )

    pdfs = root / "pdfs"
    pdfs.mkdir()
    pdf_content = b"%PDF-1.4\nfixture\n%%EOF\n"
    (pdfs / "example2026.pdf").write_bytes(pdf_content)
    import hashlib

    discovery = root / "source-discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "matches": [
                    {
                        "citekey": "example2026",
                        "sha256": hashlib.sha256(pdf_content).hexdigest(),
                        "match_basis": "fixture source identity",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manuscript = root / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(
        "\\cite{example2026}\n",
        encoding="utf-8",
    )

    ingestion = root / "ingestion"
    transcript = ingestion / "example2026" / "derived" / "transcription"
    transcript.mkdir(parents=True)
    (ingestion / "example2026" / "extraction.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (transcript / "manifest.json").write_text(
        '{"status":"automated_unreviewed"}\n', encoding="utf-8"
    )
    (transcript / "audit.json").write_text(
        '{"status":"passed"}\n', encoding="utf-8"
    )
    (transcript / "clean.json").write_text("{}\n", encoding="utf-8")
    (transcript / "clean.txt").write_text("evidence\n", encoding="utf-8")

    coverage = CoverageObservation.create(
        asserted_source_revision=_ASSERTED_REVISION,
        state=CoverageState.COMPLETE,
        authorized_root_aliases=("papers",),
        exclusions=(),
        failures=(),
        ambiguity_evaluation=AmbiguityEvaluation.EVALUATED,
        references=(
            ReferenceCoverage(
                citekey="example2026",
                no_match=True,
                access_state=CoverageAccessState.NONE,
                candidates=(),
                evidence=("bounded-fixture-search",),
            ),
        ),
    )
    coverage_path = root / "coverage.json"
    coverage_path.write_text(coverage.to_json(), encoding="utf-8")
    return {
        "bibliography": bibliography,
        "corpus": corpus,
        "pdfs": pdfs,
        "discovery": discovery,
        "manuscript": manuscript,
        "ingestion": ingestion,
        "coverage": coverage_path,
    }


def _reconcile(paths: dict[str, Path]):
    coverage_bytes = paths["coverage"].read_bytes()
    coverage = CoverageObservation.from_json(coverage_bytes.decode("utf-8"))
    closure = build_citation_closure(
        paths["manuscript"],
        bibliography_keys=("example2026",),
        source_revision=_ASSERTED_REVISION,
    )
    return reconcile_collection(
        (_record(),),
        bibliography_bytes=paths["bibliography"].read_bytes(),
        collection_id="fixture",
        source_revision=_ASSERTED_REVISION,
        collection_rows=load_collection_rows(paths["corpus"]),
        managed_pdfs=scan_managed_pdfs(
            paths["pdfs"], source_discovery=paths["discovery"]
        ),
        citation_closure=closure,
        coverage_observation=coverage,
        coverage_observation_bytes=coverage_bytes,
        processing_evidence=scan_processing_evidence(
            paths["ingestion"], citekeys=("example2026",)
        ),
        bibliography_parser="pybtex@test-version",
    )


def test__package_manifest__covers_all_payload_outputs_and_bound_inputs(
    tmp_path: Path,
) -> None:
    paths = _prepare_inputs(tmp_path / "inputs")
    outputs = _reconcile(paths)
    package = outputs.package_manifest
    files = dict(outputs.files)

    assert set(files) == {
        PACKAGE_MANIFEST_FILENAME,
        "collection-manifest.json",
        "citation-closure.json",
        "coverage-observation.json",
        "missing-pdfs.csv",
        "ambiguous-pdfs.csv",
        "extra-pdfs.csv",
    }
    assert {item.filename for item in package.outputs} == set(files) - {
        PACKAGE_MANIFEST_FILENAME
    }
    for item in package.outputs:
        content = files[item.filename]
        assert item.byte_size == len(content)
        import hashlib

        assert item.sha256 == hashlib.sha256(content).hexdigest()

    roles = {item.role for item in package.inputs}
    assert {
        "bibliography",
        "collection-rows",
        "source-discovery",
        "managed-asset",
        "citation-source",
        "citation-closure",
        "coverage-observation",
        "processing-source",
        "processing-observation",
        "normalized-reconciliation-input",
    } <= roles
    assert package.asserted_source_revision == _ASSERTED_REVISION
    assert package.verified_source_tree is None
    assert package.generator.name == "projectkoios-references"
    assert {item.name for item in package.components} >= {
        "bibliography-parser",
        "collection-reconciliation",
        "latex-citation-parser",
    }
    assert str(tmp_path) not in package.to_json()
    assert "derived/transcription" not in package.to_json()

    changed_payload = {
        name: content
        for name, content in files.items()
        if name != PACKAGE_MANIFEST_FILENAME
    }
    changed_payload["missing-pdfs.csv"] += b"changed output\n"
    changed_package = type(package).create(
        collection_id=package.collection_id,
        asserted_source_revision=package.asserted_source_revision,
        verified_source_tree=package.verified_source_tree,
        components=package.components,
        inputs=package.inputs,
        output_files=changed_payload,
    )
    assert changed_package.package_id != package.package_id


def test__package_identity__changes_for_every_bound_input_byte_class(
    tmp_path: Path,
) -> None:
    paths = _prepare_inputs(tmp_path / "inputs")
    baseline = _reconcile(paths).package_manifest.package_id

    mutations = (
        (paths["bibliography"], b"% byte-only bibliography change\n"),
        (paths["corpus"], b"\n"),
        (paths["discovery"], b" "),
        (paths["pdfs"] / "example2026.pdf", b"% changed asset bytes\n"),
        (paths["manuscript"] / "main.tex", b"% source byte change\n"),
        (
            paths["ingestion"]
            / "example2026"
            / "derived"
            / "transcription"
            / "clean.txt",
            b"changed processing bytes\n",
        ),
        (paths["coverage"], b" "),
    )
    for path, suffix in mutations:
        original = path.read_bytes()
        path.write_bytes(original + suffix)
        assert _reconcile(paths).package_manifest.package_id != baseline
        path.write_bytes(original)


def test__package_identity__binds_citation_closure_even_when_statuses_match(
    tmp_path: Path,
) -> None:
    paths = _prepare_inputs(tmp_path / "inputs")
    first = _reconcile(paths)
    source = paths["manuscript"] / "main.tex"
    source.rename(paths["manuscript"] / "renamed.tex")
    second = _reconcile(paths)

    assert first.manifest.counts == second.manifest.counts
    assert (
        first.package_manifest.package_id != second.package_manifest.package_id
    )


def test__package_parse_verify_replay_and_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    outputs = _reconcile(_prepare_inputs(tmp_path / "inputs"))
    destination = tmp_path / "published" / "fixture"
    replay = tmp_path / "replay" / "fixture"

    created = publish_reconciliation(outputs, output_directory=destination)
    loaded = verify_reconciliation_package(
        destination, expected_package_id=created.package_id
    )
    parsed = parse_reconciliation_package(
        (destination / PACKAGE_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert loaded.manifest == parsed == outputs.package_manifest
    assert (
        replay_reconciliation(outputs, output_directory=replay).status
        == "created"
    )
    assert (
        replay_reconciliation(outputs, output_directory=replay).status
        == "unchanged"
    )
    assert dict(loaded.files) == dict(outputs.files)

    payload = destination / "missing-pdfs.csv"
    original_payload = payload.read_bytes()
    payload.write_bytes(original_payload + b"tampered\n")
    with pytest.raises(CollectionReconciliationError, match="output differs"):
        verify_reconciliation_package(destination)
    payload.write_bytes(original_payload)

    manifest_path = destination / PACKAGE_MANIFEST_FILENAME
    original_manifest = manifest_path.read_bytes()
    manifest_path.write_bytes(original_manifest + b"\n")
    with pytest.raises(CollectionReconciliationError, match="canonical"):
        verify_reconciliation_package(destination)
    manifest_path.write_bytes(original_manifest)

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["asserted_source_revision"] = "tampered"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(CollectionReconciliationError, match="identity"):
        verify_reconciliation_package(destination)


def test__package_publication__rejects_incomplete_or_extra_destination(
    tmp_path: Path,
) -> None:
    outputs = _reconcile(_prepare_inputs(tmp_path / "inputs"))
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / PACKAGE_MANIFEST_FILENAME).write_bytes(
        dict(outputs.files)[PACKAGE_MANIFEST_FILENAME]
    )
    with pytest.raises(CollectionReconciliationError, match="incomplete"):
        publish_reconciliation(outputs, output_directory=incomplete)

    complete = tmp_path / "complete"
    publish_reconciliation(outputs, output_directory=complete)
    (complete / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(CollectionReconciliationError, match="incomplete"):
        publish_reconciliation(outputs, output_directory=complete)


def test__content_identified_records__have_immutable_nested_state(
    tmp_path: Path,
) -> None:
    outputs = _reconcile(_prepare_inputs(tmp_path / "inputs"))
    counts = outputs.manifest.counts
    expected_counts = dict(counts)

    with pytest.raises(TypeError):
        counts["references"] = 9  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        counts._items = (("references", 999),)  # type: ignore[misc]
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        counts._mapping = {"references": 999}  # type: ignore[attr-defined]
    assert dict(counts) == expected_counts

    with pytest.raises(FrozenInstanceError):
        outputs.package_manifest.inputs = ()  # type: ignore[misc]
    with pytest.raises(ValueError, match="software-identity tuple"):
        replace(
            outputs.package_manifest,
            components=list(outputs.package_manifest.components),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="software-identity tuple"):
        replace(
            outputs.package_manifest,
            components=(object(),),  # type: ignore[arg-type]
        )

    _assert_no_mutable_nested_containers(outputs)


def _assert_no_mutable_nested_containers(value: object) -> None:
    assert not isinstance(value, (dict, list, set))
    if isinstance(value, FrozenCounts):
        _assert_no_mutable_nested_containers(tuple(value.items()))
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            _assert_no_mutable_nested_containers(getattr(value, item.name))
    elif isinstance(value, tuple):
        for item in value:
            _assert_no_mutable_nested_containers(item)


def test__source_revision__is_asserted_unless_git_identity_is_verified(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    manuscript = repository / "manuscript"
    manuscript.mkdir()
    source = manuscript / "main.tex"
    source.write_text("\\cite{example2026}\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        cwd=repository,
        check=True,
    )
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    verified = build_citation_closure(
        manuscript,
        bibliography_keys=("example2026",),
        source_revision=head,
    )
    assert verified.asserted_source_revision == head
    assert verified.verified_source_tree is not None
    assert verified.verified_source_tree.commit_id == head

    source.write_text("\\cite{example2026}\n% dirty\n", encoding="utf-8")
    dirty = build_citation_closure(
        manuscript,
        bibliography_keys=("example2026",),
        source_revision=head,
    )
    assert dirty.asserted_source_revision == head
    assert dirty.verified_source_tree is None
    assert dirty.source_file_evidence != verified.source_file_evidence
