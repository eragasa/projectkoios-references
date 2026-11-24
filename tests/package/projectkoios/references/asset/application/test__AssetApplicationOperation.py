from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.asset.application.action import (
    ASSET_APPLICATION_OPERATION_ACTION_ID,
    AssetApplicationOperation,
)
from projectkoios.references.asset.application.error import (
    AssetApplicationError,
)
from projectkoios.references.asset.application.request import (
    AssetApplicationOperationRequest,
)
from projectkoios.references.asset.application.result import (
    AssetApplicationOperationResult,
)
from projectkoios.references.assets import (
    AssetDiscoveryPlanner,
    SearchRoot,
)
from projectkoios.references.catalog import (
    CatalogConflictError,
    ReferenceCatalog,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.path_safety import RootStorageClass
from test_asset_authorization_helpers import authorize_asset

from scripts.koios_ref import main


def _fixture(
    root: Path,
    *,
    with_catalog: bool = True,
) -> tuple[AssetApplicationOperationRequest, ReferenceCandidate]:
    root.mkdir()
    entry = "@article{synthetic2026, title={Synthetic Asset}}\n"
    observation = SourceBibliographyObservation.create(
        source_id="synthetic-asset-application",
        asserted_source_revision="synthetic-revision",
        source_path="references.bib",
        bibliography_bytes=entry.encode(),
        entry_index=0,
        observed_citekey="synthetic2026",
        verbatim_entry=entry,
        parser=ProducerIdentity("synthetic-parser", "1"),
    )
    candidate = ReferenceCandidate.create(
        proposed_citekey="synthetic2026",
        entry_type="article",
        title="Synthetic Asset",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=(observation.observation_id,),
        generator=ProducerIdentity("synthetic-normalizer", "1"),
    )
    source_root = root / "source"
    source_root.mkdir()
    (source_root / "synthetic2026.pdf").write_bytes(
        b"%PDF runtime-neutral asset fixture"
    )
    search_roots = (SearchRoot("papers", source_root, RootStorageClass.LOCAL),)
    plan = AssetDiscoveryPlanner().scan((candidate,), search_roots)
    authorization, projection = authorize_asset(
        plan, plan.candidates[0], candidate
    )
    plan_path = root / "plan.json"
    authorization_path = root / "authorization.json"
    identity_path = root / "identity.json"
    plan_path.write_text(plan.to_json(), encoding="utf-8")
    authorization_path.write_text(authorization.to_json(), encoding="utf-8")
    identity_path.write_text(projection.to_json(), encoding="utf-8")

    catalog_path = root / "catalog.sqlite3" if with_catalog else None
    catalog_storage_class = RootStorageClass.LOCAL if with_catalog else None
    if catalog_path is not None:
        catalog = ReferenceCatalog(
            catalog_path, storage_class=RootStorageClass.LOCAL
        )
        catalog.initialize()
        catalog.import_candidates((candidate,), (observation,))

    return (
        AssetApplicationOperationRequest(
            plan=plan_path,
            plan_storage_class=RootStorageClass.LOCAL,
            authorization=authorization_path,
            authorization_storage_class=RootStorageClass.LOCAL,
            identity_projection=identity_path,
            identity_projection_storage_class=RootStorageClass.LOCAL,
            citekey="synthetic2026",
            candidate_path=None,
            search_roots=search_roots,
            destination=root / "destination",
            destination_storage_class=RootStorageClass.LOCAL,
            rights_status="private-local",
            catalog=catalog_path,
            catalog_storage_class=catalog_storage_class,
        ),
        candidate,
    )


def _cli_arguments(request: AssetApplicationOperationRequest) -> list[str]:
    arguments = [
        "assets-apply",
        str(request.plan),
        request.citekey,
        str(request.destination),
        "--plan-storage-class",
        request.plan_storage_class.value,
        "--destination-storage-class",
        request.destination_storage_class.value,
        "--search-root",
        (
            f"{request.search_roots[0].storage_class.value}:"
            f"{request.search_roots[0].alias}={request.search_roots[0].path}"
        ),
        "--authorization",
        str(request.authorization),
        "--authorization-storage-class",
        request.authorization_storage_class.value,
        "--identity-projection",
        str(request.identity_projection),
        "--identity-projection-storage-class",
        request.identity_projection_storage_class.value,
        "--rights-status",
        request.rights_status,
    ]
    if request.catalog is not None:
        assert request.catalog_storage_class is not None
        arguments.extend(
            (
                "--catalog",
                str(request.catalog),
                "--catalog-storage-class",
                request.catalog_storage_class.value,
            )
        )
    return arguments


def test__asset_application__uses_typed_owner_contracts() -> None:
    assert issubclass(AssetApplicationOperationRequest, DataObjectActionRequest)
    assert issubclass(AssetApplicationOperationResult, DataObjectActionResult)
    assert issubclass(AssetApplicationOperation, DataObjectActionizer)
    assert (
        AssetApplicationOperation.action_id
        == ASSET_APPLICATION_OPERATION_ACTION_ID
    )
    methods = {
        name
        for name, value in vars(AssetApplicationOperation).items()
        if callable(value) and not name.startswith("__")
    }
    assert methods == {"action"}


def test__asset_application__replays_and_rebuilds_semantically(
    tmp_path: Path,
) -> None:
    request_a, _candidate_a = _fixture(tmp_path / "a")
    operation = AssetApplicationOperation()

    first = operation.action(request=request_a)
    replayed = operation.action(request=request_a)

    assert first.materialization.created is True
    assert replayed.materialization.created is False
    assert first.plan.plan_id == replayed.plan.plan_id
    assert first.authorization.decision_id == replayed.authorization.decision_id
    assert first.catalog_record == replayed.catalog_record
    assert first.catalog_record_present is True
    assert first.materialization.path.read_bytes() == (
        b"%PDF runtime-neutral asset fixture"
    )
    assert (
        len(
            ReferenceCatalog(
                request_a.catalog,  # type: ignore[arg-type]
                storage_class=RootStorageClass.LOCAL,
            ).read_source_assets()
        )
        == 1
    )

    request_b, _candidate_b = _fixture(tmp_path / "b")
    rebuilt = operation.action(request=request_b)
    assert rebuilt.materialization.created is True
    assert first.plan.plan_id == rebuilt.plan.plan_id
    assert first.authorization.decision_id == rebuilt.authorization.decision_id
    assert first.candidate == rebuilt.candidate
    assert first.catalog_record == rebuilt.catalog_record
    assert (
        first.materialization.path.read_bytes()
        == rebuilt.materialization.path.read_bytes()
    )


def test__asset_application__supports_explicit_no_catalog_application(
    tmp_path: Path,
) -> None:
    request, _candidate = _fixture(tmp_path / "inputs", with_catalog=False)

    first = AssetApplicationOperation().action(request=request)
    replayed = AssetApplicationOperation().action(request=request)

    assert first.materialization.created is True
    assert replayed.materialization.created is False
    assert first.catalog_record_present is False
    assert replayed.catalog_record_present is False
    assert request.catalog is None
    assert request.catalog_storage_class is None


def test__assets_apply_cli__is_a_thin_equivalent_adapter(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner_request, _candidate = _fixture(tmp_path / "owner")
    cli_request, _cli_candidate = _fixture(tmp_path / "cli")

    owner = AssetApplicationOperation().action(request=owner_request)
    assert main(_cli_arguments(cli_request)) == 0

    assert capsys.readouterr().out.strip() == str(
        cli_request.destination / "synthetic2026.pdf"
    )
    assert (
        owner.catalog_record
        == ReferenceCatalog(
            cli_request.catalog,  # type: ignore[arg-type]
            storage_class=RootStorageClass.LOCAL,
        ).read_source_assets()[0]
    )
    assert (
        owner.materialization.path.read_bytes()
        == (cli_request.destination / "synthetic2026.pdf").read_bytes()
    )


def test__asset_application__rejects_incomplete_capabilities_before_effects(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "destination"
    catalog = tmp_path / "catalog.sqlite3"

    with pytest.raises(AssetApplicationError, match="supplied together"):
        AssetApplicationOperationRequest(
            plan=tmp_path / "missing-plan.json",
            plan_storage_class=RootStorageClass.LOCAL,
            authorization=tmp_path / "missing-authorization.json",
            authorization_storage_class=RootStorageClass.LOCAL,
            identity_projection=tmp_path / "missing-identity.json",
            identity_projection_storage_class=RootStorageClass.LOCAL,
            citekey="synthetic2026",
            candidate_path=None,
            search_roots=(
                SearchRoot("papers", tmp_path, RootStorageClass.LOCAL),
            ),
            destination=destination,
            destination_storage_class=RootStorageClass.LOCAL,
            rights_status="private-local",
            catalog=catalog,
            catalog_storage_class=None,
        )

    assert not destination.exists()
    assert not catalog.exists()


def test__asset_application__rejects_selector_before_effects(
    tmp_path: Path,
) -> None:
    request, _candidate = _fixture(tmp_path / "inputs")
    wrong_selector = AssetApplicationOperationRequest(
        plan=request.plan,
        plan_storage_class=request.plan_storage_class,
        authorization=request.authorization,
        authorization_storage_class=request.authorization_storage_class,
        identity_projection=request.identity_projection,
        identity_projection_storage_class=(
            request.identity_projection_storage_class
        ),
        citekey="different2026",
        candidate_path=None,
        search_roots=request.search_roots,
        destination=request.destination,
        destination_storage_class=request.destination_storage_class,
        rights_status=request.rights_status,
        catalog=request.catalog,
        catalog_storage_class=request.catalog_storage_class,
    )

    with pytest.raises(AssetApplicationError, match="exactly one"):
        AssetApplicationOperation().action(request=wrong_selector)

    assert not request.destination.exists()
    assert (
        ReferenceCatalog(
            request.catalog,  # type: ignore[arg-type]
            storage_class=RootStorageClass.LOCAL,
        ).read_source_assets()
        == ()
    )


def test__asset_application__reconciles_after_post_copy_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _candidate = _fixture(tmp_path / "inputs")
    original = ReferenceCatalog.source_asset_recording_transaction

    @contextmanager
    def failing_recording(
        self: ReferenceCatalog,
        asset: object,
    ):  # type: ignore[no-untyped-def]
        with original(self, asset):  # type: ignore[arg-type]
            yield
            raise CatalogConflictError("synthetic post-copy commit failure")

    monkeypatch.setattr(
        ReferenceCatalog,
        "source_asset_recording_transaction",
        failing_recording,
    )
    with pytest.raises(CatalogConflictError, match="post-copy"):
        AssetApplicationOperation().action(request=request)

    destination = request.destination / "synthetic2026.pdf"
    assert destination.read_bytes() == b"%PDF runtime-neutral asset fixture"
    assert (
        ReferenceCatalog(
            request.catalog,  # type: ignore[arg-type]
            storage_class=RootStorageClass.LOCAL,
        ).read_source_assets()
        == ()
    )

    monkeypatch.setattr(
        ReferenceCatalog,
        "source_asset_recording_transaction",
        original,
    )
    reconciled = AssetApplicationOperation().action(request=request)
    assert reconciled.materialization.created is False
    assert reconciled.catalog_record_present is True
    assert ReferenceCatalog(
        request.catalog,  # type: ignore[arg-type]
        storage_class=RootStorageClass.LOCAL,
    ).read_source_assets() == (reconciled.catalog_record,)
