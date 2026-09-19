from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from pathlib import Path

import pytest
from projectkoios.references.collection_reconciliation import (
    CollectionReconciliationError,
    parse_reconciliation_package,
    reconcile_collection,
)
from projectkoios.references.collection_reconciliation import (
    build_citation_closure as _build_citation_closure,
)
from projectkoios.references.collection_reconciliation import (
    load_collection_rows as _load_collection_rows,
)
from projectkoios.references.collection_reconciliation import (
    publish_reconciliation as _publish_reconciliation,
)
from projectkoios.references.collection_reconciliation import (
    replay_reconciliation as _replay_reconciliation,
)
from projectkoios.references.collection_reconciliation import (
    scan_managed_pdfs as _scan_managed_pdfs,
)
from projectkoios.references.collection_reconciliation import (
    verify_reconciliation_package as _verify_reconciliation_package,
)
from projectkoios.references.coverage import (
    AmbiguityEvaluation,
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)
from projectkoios.references.ingestion_evidence import (
    IngestionEvidenceVerificationError,
    load_ingestion_reference_evidence,
)
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput as _ReferenceEvidenceInput,
)
from projectkoios.references.io_limits import ReferenceIOLimitError
from projectkoios.references.path_safety import RootStorageClass
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    FrozenCounts,
)


def ReferenceEvidenceInput(citekey: str, path: Path) -> _ReferenceEvidenceInput:
    return _ReferenceEvidenceInput(citekey, path, RootStorageClass.LOCAL)


def build_citation_closure(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _build_citation_closure(*args, **kwargs)  # type: ignore[arg-type]


def scan_managed_pdfs(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    if kwargs.get("source_discovery") is not None:
        kwargs["source_discovery_storage_class"] = RootStorageClass.LOCAL
    return _scan_managed_pdfs(*args, **kwargs)  # type: ignore[arg-type]


def load_collection_rows(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _load_collection_rows(*args, **kwargs)  # type: ignore[arg-type]


def publish_reconciliation(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["output_storage_class"] = RootStorageClass.LOCAL
    return _publish_reconciliation(*args, **kwargs)  # type: ignore[arg-type]


def replay_reconciliation(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["output_storage_class"] = RootStorageClass.LOCAL
    return _replay_reconciliation(*args, **kwargs)  # type: ignore[arg-type]


def verify_reconciliation_package(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _verify_reconciliation_package(*args, **kwargs)  # type: ignore[arg-type]


_ASSERTED_REVISION = "caller-asserted-revision"
_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "ingestion-reference-evidence"
    / "complete.json"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reidentify(value: dict[str, object]) -> bytes:
    identity = dict(value)
    identity.pop("record_id", None)
    digest = hashlib.sha256(_canonical([identity])).hexdigest()
    value["record_id"] = f"reference-evidence-record:sha256:{digest}"
    return _canonical(value)


def _reference_evidence_for_source(content: bytes) -> bytes:
    value = json.loads(_FIXTURE.read_bytes())
    digest = hashlib.sha256(content).hexdigest()
    value["source"] = {
        "blob_id": f"blob:sha256:{digest}",
        "hash_algorithm": "sha256",
        "content_sha256": digest,
        "byte_length": len(content),
        "media_type": "application/pdf",
    }
    return _reidentify(value)


def _record() -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="example2026",
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
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

    evidence = root / "reference-evidence.json"
    evidence.write_bytes(_reference_evidence_for_source(pdf_content))

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
        "evidence": evidence,
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
    managed = scan_managed_pdfs(
        paths["pdfs"], source_discovery=paths["discovery"]
    )
    return reconcile_collection(
        (_record(),),
        bibliography_bytes=paths["bibliography"].read_bytes(),
        collection_id="fixture",
        source_revision=_ASSERTED_REVISION,
        collection_rows=load_collection_rows(paths["corpus"]),
        managed_pdfs=managed,
        citation_closure=closure,
        coverage_observation=coverage,
        coverage_observation_bytes=coverage_bytes,
        processing_evidence=load_ingestion_reference_evidence(
            (ReferenceEvidenceInput("example2026", paths["evidence"]),),
            managed_pdfs=managed,
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
        "reference-state-projections.json",
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
        "ingestion-reference-evidence",
        "processing-observation",
        "normalized-reconciliation-input",
        "effective-io-limits",
    } <= roles
    evidence_input = next(
        item
        for item in package.inputs
        if item.role == "ingestion-reference-evidence"
    )
    evidence_bytes = paths["evidence"].read_bytes()
    assert evidence_input.filename == (
        "inputs/ingestion-reference-evidence/example2026.json"
    )
    assert evidence_input.byte_size == len(evidence_bytes)
    assert evidence_input.sha256 == hashlib.sha256(evidence_bytes).hexdigest()
    assert package.asserted_source_revision == _ASSERTED_REVISION
    assert package.verified_source_tree is None
    assert package.generator.name == "projectkoios-references"
    assert {item.name for item in package.components} >= {
        "bibliography-parser",
        "collection-reconciliation",
        "latex-citation-parser",
        "reference-io-limits",
    }
    assert str(tmp_path) not in package.to_json()
    assert "projectkoios.ingestion.reference-evidence" in (
        paths["evidence"].read_text(encoding="utf-8")
    )

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
        (paths["manuscript"] / "main.tex", b"% source byte change\n"),
        (paths["coverage"], b" "),
    )
    for path, suffix in mutations:
        original = path.read_bytes()
        path.write_bytes(original + suffix)
        assert _reconcile(paths).package_manifest.package_id != baseline
        path.write_bytes(original)

    pdf_path = paths["pdfs"] / "example2026.pdf"
    original_pdf = pdf_path.read_bytes()
    pdf_path.write_bytes(original_pdf + b"% changed asset bytes\n")
    with pytest.raises(
        IngestionEvidenceVerificationError,
        match="managed PDF identity",
    ):
        _reconcile(paths)
    pdf_path.write_bytes(original_pdf)

    evidence_path = paths["evidence"]
    original_evidence = evidence_path.read_bytes()
    value = json.loads(original_evidence)
    value["transcript"]["warning_count"] += 1
    evidence_path.write_bytes(_reidentify(value))
    assert _reconcile(paths).package_manifest.package_id != baseline
    evidence_path.write_bytes(original_evidence)


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

    over_limit = tmp_path / "over-limit"
    publish_reconciliation(outputs, output_directory=over_limit)
    oversized = over_limit / "missing-pdfs.csv"
    oversized.write_bytes(b"")
    with oversized.open("r+b") as stream:
        stream.truncate(50_000_001)
    with pytest.raises(ReferenceIOLimitError) as caught:
        publish_reconciliation(outputs, output_directory=over_limit)
    assert caught.value.coverage_status == "incomplete"
    assert caught.value.limit_name == "max_file_bytes"


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
