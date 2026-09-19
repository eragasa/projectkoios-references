from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
from projectkoios.references import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    CloudRootMutationError,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    ProducerIdentity,
    ReferenceCandidate,
    RootPreflightEvidence,
    RootStorageClass,
)
from projectkoios.references.acquisition import create_acquisition_manifest
from projectkoios.references.assets import (
    AssetDiscoveryPlanner,
    SearchRoot,
    materialize_asset,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.cli import main
from projectkoios.references.collection_reconciliation import (
    CollectionReconciliationError,
    ManagedPdfScan,
    build_citation_closure,
    reconcile_collection,
    scan_managed_pdfs,
)
from projectkoios.references.path_safety import read_path_bytes
from projectkoios.references.validation import validate_reference_objects


class SyntheticProbe(CloudPlaceholderProbe):
    probe_id = "synthetic-placeholder-probe-v1"

    def __init__(
        self,
        statuses: dict[str, PlaceholderStatus] | None = None,
        *,
        support: PlaceholderProbeSupport = PlaceholderProbeSupport.SUPPORTED,
    ) -> None:
        self.statuses = statuses or {}
        self.support_status = support
        self.calls: list[tuple[str, str | None]] = []

    def support(self, *, root_alias: str) -> PlaceholderProbeSupport:
        self.calls.append((root_alias, None))
        return self.support_status

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        rendered = relative_path.as_posix()
        self.calls.append((root_alias, rendered))
        return self.statuses.get(rendered, PlaceholderStatus.ORDINARY_FILE)


def _record(citekey: str = "example2026") -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey=citekey,
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("synthetic-fixture", "1"),
    )


def _acquisition_row() -> dict[str, str]:
    return {
        "proposed_citekey": "example2026",
        "root_alias": "streaming",
        "relative_path": "example2026.pdf",
        "rights_status": "unreviewed",
        "asset_status": "cloud-placeholder",
        "identity_status": "unaccepted-candidate",
    }


def test__unsupported_cloud_root__fails_before_filesystem_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("unsupported cloud root was opened")

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.open", forbidden_open
    )
    root = SearchRoot(
        "streaming",
        tmp_path / "not-opened",
        RootStorageClass.CLOUD_BACKED,
    )

    with pytest.raises(PlaceholderPreflightError) as caught:
        AssetDiscoveryPlanner().scan((_record(),), (root,))

    assert (
        caught.value.observation.status
        is PlaceholderStatus.UNSUPPORTED_PLATFORM
    )
    assert caught.value.observation.relative_path is None
    assert caught.value.observation.root_alias == "streaming"
    assert not opened


def test__standalone_cloud_path__fails_before_parent_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("unsupported standalone path parent was opened")

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.open", forbidden_open
    )
    with pytest.raises(PlaceholderPreflightError) as caught:
        read_path_bytes(
            tmp_path / "placeholder.pdf",
            label="standalone fixture",
            root_alias="standalone-fixture",
            storage_class=RootStorageClass.CLOUD_BACKED,
        )
    assert caught.value.coverage_status == "incomplete"
    assert not opened


@pytest.mark.parametrize(
    "status",
    (
        PlaceholderStatus.MISSING,
        PlaceholderStatus.ACCESS_CONTROLLED,
        PlaceholderStatus.UNREADABLE,
    ),
)
def test__standalone_cloud_nonordinary_status__remains_typed_incomplete(
    tmp_path: Path,
    status: PlaceholderStatus,
) -> None:
    parent = tmp_path / "cloud-parent"
    parent.mkdir()
    probe = SyntheticProbe({"candidate.pdf": status})

    with pytest.raises(PlaceholderPreflightError) as caught:
        read_path_bytes(
            parent / "candidate.pdf",
            label="standalone cloud candidate",
            root_alias="standalone-cloud-candidate",
            storage_class=RootStorageClass.CLOUD_BACKED,
            placeholder_probe=probe,
        )

    assert caught.value.observation.status is status
    assert caught.value.coverage_status == "incomplete"
    assert str(tmp_path) not in caught.value.to_json()


def test__cloud_mutations__fail_before_filesystem_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SyntheticProbe()
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("cloud mutation touched the filesystem")

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.open", forbidden_open
    )
    with pytest.raises(CloudRootMutationError):
        ReferenceCatalog(
            tmp_path / "cloud.sqlite3",
            storage_class=RootStorageClass.CLOUD_BACKED,
            placeholder_probe=probe,
        )
    with pytest.raises(CloudRootMutationError):
        AuthorizedRoot.create(
            tmp_path / "cloud-output",
            label="cloud output",
            root_alias="cloud-output",
            storage_class=RootStorageClass.CLOUD_BACKED,
            placeholder_probe=probe,
        )
    assert not opened


def test__bound_cloud_mutation_methods_are_forbidden(tmp_path: Path) -> None:
    root_path = tmp_path / "cloud-root"
    root_path.mkdir()
    (root_path / "source.pdf").write_bytes(b"synthetic")
    probe = SyntheticProbe()
    root = AuthorizedRoot.existing(
        root_path,
        label="cloud root",
        root_alias="cloud-root",
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=probe,
    )
    local = AuthorizedRoot.existing(
        root_path,
        label="local source",
        root_alias="local-source",
        storage_class=RootStorageClass.LOCAL,
    )
    with pytest.raises(CloudRootMutationError):
        root.create_directory("child")
    with pytest.raises(CloudRootMutationError):
        root.rename_child("source.pdf", "renamed.pdf")
    with pytest.raises(CloudRootMutationError):
        root.write_bytes("result.pdf", b"bytes", replace=False)
    with pytest.raises(CloudRootMutationError):
        root.copy_file_from(
            local,
            "source.pdf",
            "copy.pdf",
            max_bytes=100,
            expected_sha256="0" * 64,
            expected_size=9,
        )
    assert sorted(path.name for path in root_path.iterdir()) == ["source.pdf"]


def test__asset_scan__fails_incomplete_without_open_read_or_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mixed-root"
    source.mkdir()
    (source / "example2026.pdf").write_bytes(b"synthetic placeholder stub")
    probe = SyntheticProbe(
        {"example2026.pdf": PlaceholderStatus.CLOUD_PLACEHOLDER}
    )

    def forbidden_observe(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("placeholder reached hashing/open path")

    monkeypatch.setattr(AuthorizedRoot, "observe_file", forbidden_observe)
    with pytest.raises(PlaceholderPreflightError) as caught:
        AssetDiscoveryPlanner().scan(
            (_record(),),
            (
                SearchRoot(
                    "streaming",
                    source,
                    RootStorageClass.CLOUD_BACKED,
                    probe,
                ),
            ),
        )

    observation = caught.value.observation
    assert observation.status is PlaceholderStatus.CLOUD_PLACEHOLDER
    assert observation.relative_path == "example2026.pdf"
    assert observation.storage_class is RootStorageClass.CLOUD_BACKED
    diagnostic = caught.value.to_dict()
    assert diagnostic["coverage_status"] == "incomplete"
    assert diagnostic["probe_id"] == probe.probe_id
    assert str(tmp_path) not in caught.value.to_json()


def test__complete_plan_parser__rejects_skipped_placeholder_observation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "local"
    source.mkdir()
    (source / "example2026.pdf").write_bytes(b"%PDF synthetic")
    plan = AssetDiscoveryPlanner().scan(
        (_record(),),
        (SearchRoot("local", source, RootStorageClass.LOCAL),),
    )
    payload = json.loads(plan.to_json())
    payload["file_observations"] = [
        {
            "root_alias": "local",
            "relative_path": "skipped.pdf",
            "storage_class": "local",
            "probe_id": "local-root-no-cloud-probe-v1",
            "status": "unreadable",
        }
    ]
    with pytest.raises(ValueError, match="complete asset plans"):
        type(plan).from_json(json.dumps(payload))


def test__acquisition_and_managed_scan__fail_typed_without_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mixed-root"
    source.mkdir()
    (source / "example2026.pdf").write_bytes(b"synthetic placeholder stub")
    probe = SyntheticProbe(
        {"example2026.pdf": PlaceholderStatus.CLOUD_PLACEHOLDER}
    )
    root = SearchRoot(
        "streaming",
        source,
        RootStorageClass.CLOUD_BACKED,
        probe,
    )

    def forbidden_observe(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("placeholder reached byte observation")

    monkeypatch.setattr(AuthorizedRoot, "observe_file", forbidden_observe)
    with pytest.raises(PlaceholderPreflightError) as caught:
        create_acquisition_manifest(
            source_id="synthetic",
            rows=(_acquisition_row(),),
            roots=(root,),
        )
    assert (
        caught.value.observation.status is PlaceholderStatus.CLOUD_PLACEHOLDER
    )

    with pytest.raises(PlaceholderPreflightError) as managed_failure:
        scan_managed_pdfs(
            source,
            storage_class=RootStorageClass.CLOUD_BACKED,
            placeholder_probe=probe,
        )
    assert (
        managed_failure.value.observation.status
        is PlaceholderStatus.CLOUD_PLACEHOLDER
    )
    assert managed_failure.value.coverage_status == "incomplete"
    assert str(tmp_path) not in managed_failure.value.to_json()


def test__managed_scan_and_reconcile__reject_skipped_observations() -> None:
    root_preflight = RootPreflightEvidence(
        root_alias="managed-pdfs",
        storage_class=RootStorageClass.LOCAL,
        probe_id="local-root-no-cloud-probe-v1",
        probe_support=None,
    )
    skipped = PlaceholderObservation(
        root_alias="managed-pdfs",
        relative_path="skipped.pdf",
        storage_class=RootStorageClass.LOCAL,
        probe_id="local-root-no-cloud-probe-v1",
        status=PlaceholderStatus.UNREADABLE,
    )
    with pytest.raises(ValueError, match="cannot contain skipped"):
        ManagedPdfScan(
            pdfs=(),
            input_evidence=(),
            root_preflight=root_preflight,
            file_observations=(skipped,),
        )

    invalid = object.__new__(ManagedPdfScan)
    object.__setattr__(invalid, "pdfs", ())
    object.__setattr__(invalid, "input_evidence", ())
    object.__setattr__(invalid, "root_preflight", root_preflight)
    object.__setattr__(invalid, "file_observations", (skipped,))
    with pytest.raises(
        CollectionReconciliationError,
        match="cannot consume skipped",
    ):
        reconcile_collection(
            (),
            bibliography_bytes=b"",
            collection_id="synthetic",
            source_revision="asserted",
            collection_rows={},
            managed_pdfs=invalid,
            citation_closure=None,
        )


def test__cloud_manuscript_verification__never_invokes_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "main.tex").write_text(
        r"Synthetic citation \cite{example2026}.",
        encoding="utf-8",
    )
    probe = SyntheticProbe()
    invoked = False

    def forbidden_run(*args: object, **kwargs: object) -> None:
        nonlocal invoked
        del args, kwargs
        invoked = True
        raise AssertionError("cloud-backed source verification invoked Git")

    monkeypatch.setattr(
        "projectkoios.references.collection_reconciliation.subprocess.run",
        forbidden_run,
    )
    closure = build_citation_closure(
        manuscript,
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=probe,
        bibliography_keys=("example2026",),
        source_revision="a" * 40,
    )

    assert closure.verified_source_tree is None
    assert closure.root_preflight.storage_class is RootStorageClass.CLOUD_BACKED
    assert closure.root_preflight.probe_id == probe.probe_id
    assert not invoked


@pytest.mark.parametrize(
    "status",
    (
        PlaceholderStatus.CLOUD_PLACEHOLDER,
        PlaceholderStatus.MISSING,
        PlaceholderStatus.ACCESS_CONTROLLED,
        PlaceholderStatus.UNREADABLE,
    ),
)
def test__materialization_rechecks_preflight_before_destination_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: PlaceholderStatus,
) -> None:
    local = tmp_path / "local"
    local.mkdir()
    source = local / "example2026.pdf"
    source.write_bytes(b"%PDF synthetic fixture")
    probe = SyntheticProbe()
    cloud_roots = (
        SearchRoot(
            "papers",
            local,
            RootStorageClass.CLOUD_BACKED,
            probe,
        ),
    )
    plan = AssetDiscoveryPlanner().scan((_record(),), cloud_roots)
    candidate = plan.candidates[0]
    probe.statuses["example2026.pdf"] = status
    destination = tmp_path / "must-not-exist"
    opened: list[object] = []
    original_open = __import__("os").open

    def recorded_open(path: object, *args: object, **kwargs: object) -> int:
        opened.append(path)
        return original_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.open", recorded_open
    )
    with pytest.raises(PlaceholderPreflightError) as caught:
        materialize_asset(
            candidate,
            expected_root_preflight=plan.root_preflights[0],
            roots=cloud_roots,
            destination_directory=destination,
            destination_storage_class=RootStorageClass.LOCAL,
        )

    assert caught.value.observation.status is status
    assert caught.value.coverage_status == "incomplete"
    assert not destination.exists()
    assert "example2026.pdf" not in opened


def test__local_metadata_preflight__distinguishes_file_states(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "local"
    root_path.mkdir()
    ordinary = root_path / "ordinary.pdf"
    ordinary.write_bytes(b"synthetic fixture")
    unreadable = root_path / "unreadable.pdf"
    unreadable.write_bytes(b"synthetic fixture")
    unreadable.chmod(0)
    root = AuthorizedRoot.existing(
        root_path,
        label="synthetic local root",
        root_alias="synthetic-local",
        storage_class=RootStorageClass.LOCAL,
    )

    assert (
        root.preflight_file("ordinary.pdf").status
        is PlaceholderStatus.ORDINARY_FILE
    )
    assert (
        root.preflight_file("unreadable.pdf").status
        is PlaceholderStatus.UNREADABLE
    )
    assert (
        root.preflight_file("missing.pdf").status is PlaceholderStatus.MISSING
    )


@pytest.mark.parametrize(
    "status",
    (
        PlaceholderStatus.MISSING,
        PlaceholderStatus.ACCESS_CONTROLLED,
        PlaceholderStatus.UNREADABLE,
    ),
)
def test__validation__keeps_incomplete_states_typed(
    tmp_path: Path,
    status: PlaceholderStatus,
) -> None:
    notes = tmp_path / "notes"
    pdfs = tmp_path / "pdfs"
    notes.mkdir()
    pdfs.mkdir()
    (pdfs / "example2026.pdf").write_bytes(b"synthetic metadata fixture")
    probe = SyntheticProbe({"example2026.pdf": status})

    with pytest.raises(PlaceholderPreflightError) as caught:
        validate_reference_objects(
            (_record(),),
            notes_directory=notes,
            notes_storage_class=RootStorageClass.CLOUD_BACKED,
            pdf_directory=pdfs,
            pdf_storage_class=RootStorageClass.CLOUD_BACKED,
            placeholder_probe=probe,
        )

    assert caught.value.observation.status is status
    assert caught.value.coverage_status == "incomplete"
    assert str(tmp_path) not in caught.value.to_json()


def test__duplicate_cli_storage_declaration__fails_before_path_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("duplicate declaration reached path access")

    monkeypatch.setattr(
        "projectkoios.references.path_safety.os.open", forbidden_open
    )
    with pytest.raises(SystemExit, match="duplicate storage declaration"):
        main(
            [
                "validate",
                str(tmp_path / "missing.bib"),
                str(tmp_path / "missing-notes"),
                str(tmp_path / "missing-pdfs"),
                "--bibliography-storage-class",
                "local",
                "--bibliography-storage-class",
                "cloud-backed",
                "--notes-storage-class",
                "local",
                "--pdf-storage-class",
                "local",
            ]
        )
    assert not opened


def test__enrichment_cache_classification__fails_before_client_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def forbidden_client(*args: object, **kwargs: object) -> None:
        nonlocal invoked
        del args, kwargs
        invoked = True
        raise AssertionError("incomplete cache declaration reached client")

    monkeypatch.setattr(
        "projectkoios.references.cli.CrossrefClient",
        forbidden_client,
    )
    with pytest.raises(SystemExit, match="cache-storage-class"):
        main(
            [
                "enrich-crossref",
                "10.1234/synthetic",
                "--cache",
                str(tmp_path / "cache"),
            ]
        )
    assert not invoked


def test__cli__rejects_unclassified_legacy_root_syntax(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "assets-scan",
                "references.bib",
                "plan.json",
                "--search-root",
                "papers=/mixed/root",
            ]
        )
    error = capsys.readouterr().err
    assert "root storage class is required" in error
    assert "local:ALIAS=PATH" in error
