from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest
from projectkoios.references import (
    ACQUISITION_IO_LIMITS,
    ASSET_DISCOVERY_IO_LIMITS,
    METADATA_IO_LIMITS,
    AcquisitionManifest,
    AssetDiscoveryPlan,
    AssetDiscoveryPlanner,
    AuthorizedRoot,
    CitationGraphLimitError,
    GraphImportLimits,
    PathLimitError,
    ProducerIdentity,
    ReconciliationPackageLimitError,
    ReconciliationPackageManifest,
    ReferenceCandidate,
    ReferenceIOLimitError,
    RootStorageClass,
    SearchRoot,
    create_acquisition_manifest,
    materialize_asset,
)
from projectkoios.references import (
    load_bibliography as _load_bibliography,
)
from projectkoios.references import (
    load_candidate_graph as _load_candidate_graph,
)
from projectkoios.references.cli import main
from projectkoios.references.enrichment import (
    CrossrefClient as _CrossrefClient,
)
from projectkoios.references.enrichment import (
    ProviderResponseError,
    TransportRequest,
    TransportResponse,
)
from test_asset_authorization_helpers import authorize_asset


def load_bibliography(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs["storage_class"] = RootStorageClass.LOCAL
    return _load_bibliography(*args, **kwargs)  # type: ignore[arg-type]


def load_candidate_graph(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.update(
        sources_storage_class=RootStorageClass.LOCAL,
        nodes_storage_class=RootStorageClass.LOCAL,
        edges_storage_class=RootStorageClass.LOCAL,
    )
    return _load_candidate_graph(*args, **kwargs)  # type: ignore[arg-type]


def CrossrefClient(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    if kwargs.get("cache_directory") is not None:
        kwargs["cache_storage_class"] = RootStorageClass.LOCAL
    return _CrossrefClient(*args, **kwargs)  # type: ignore[arg-type]


def _record(source_digit: str = "0") -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="example2026",
        entry_type="article",
        title="Bounded Reference Input",
        authors=("Example Author",),
        year="2026",
        source_observation_ids=(
            "test-observation:sha256:" + source_digit * 64,
        ),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def _acquisition_row(relative_path: str = "example2026.pdf") -> dict[str, str]:
    return {
        "proposed_citekey": "example2026",
        "root_alias": "staging",
        "relative_path": relative_path,
        "rights_status": "rights-unreviewed",
        "asset_status": "located-local-copy",
        "identity_status": "unaccepted-candidate",
    }


def test__io_profiles__may_tighten_but_not_raise_hard_ceilings() -> None:
    tightened = replace(ASSET_DISCOVERY_IO_LIMITS, max_files=1)
    assert tightened.max_files == 1
    with pytest.raises(ValueError, match="no greater than"):
        replace(ASSET_DISCOVERY_IO_LIMITS, max_files=100_001)


def test__authorized_root__streams_digest_and_bounds_directory_before_sort(
    tmp_path: Path,
) -> None:
    content = b"%PDF-" + b"x" * 2_100_000
    (tmp_path / "large.pdf").write_bytes(content)
    root = AuthorizedRoot.existing(
        tmp_path,
        label="synthetic root",
        root_alias="synthetic-root",
        storage_class=RootStorageClass.LOCAL,
    )

    observation = root.observe_file(
        "large.pdf",
        max_bytes=len(content),
        prefix_bytes=5,
    )
    assert observation.byte_size == len(content)
    assert observation.prefix == b"%PDF-"

    with pytest.raises(PathLimitError) as failure:
        root.observe_file("large.pdf", max_bytes=len(content) - 1)
    assert failure.value.coverage_status == "incomplete"
    assert failure.value.observed == len(content)

    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    with pytest.raises(PathLimitError) as scan_failure:
        root.iter_files(
            suffix=".txt",
            recursive=False,
            max_files=10,
            max_entries=2,
            max_depth=1,
        )
    assert scan_failure.value.limit_name == "max_entries"
    assert scan_failure.value.observed == 3


def test__asset_discovery__hashes_each_file_once_and_streams_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "example2026.pdf"
    source.write_bytes(b"%PDF synthetic public fixture")
    roots = (SearchRoot("papers", source_root, RootStorageClass.LOCAL),)

    observations = 0
    original_observe = AuthorizedRoot.observe_file

    def counted_observe(
        self: AuthorizedRoot,
        relative: object,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        nonlocal observations
        observations += 1
        return original_observe(self, relative, **kwargs)  # type: ignore[arg-type]

    def forbidden_read(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        raise AssertionError("asset path attempted a whole-file read")

    monkeypatch.setattr(AuthorizedRoot, "observe_file", counted_observe)
    monkeypatch.setattr(AuthorizedRoot, "read_bytes", forbidden_read)
    plan = AssetDiscoveryPlanner().scan(
        (_record("0"), _record("1")),
        roots,
    )
    assert len(plan.candidates) == 2
    assert observations == 1
    assert plan.coverage_status == "complete"
    assert plan.effective_limits_id == plan.effective_limits.evidence_id
    assert AssetDiscoveryPlan.from_json(plan.to_json()) == plan

    selected = plan.candidates[0]
    reference_candidate = next(
        item
        for item in (_record("0"), _record("1"))
        if item.candidate_id == selected.candidate_id
    )
    authorization, projection = authorize_asset(
        plan, selected, reference_candidate
    )
    destination = materialize_asset(
        selected,
        authorization=authorization,
        plan=plan,
        identity_projection=projection,
        expected_root_preflight=plan.root_preflights[0],
        roots=roots,
        destination_directory=tmp_path / "destination",
        destination_storage_class=RootStorageClass.LOCAL,
    )
    assert destination.read_bytes() == source.read_bytes()


def test__asset_and_acquisition_limits__retain_incomplete_status(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "example2026.pdf").write_bytes(b"%PDF fixture")
    roots = (SearchRoot("staging", source, RootStorageClass.LOCAL),)
    tight = replace(ASSET_DISCOVERY_IO_LIMITS, max_file_bytes=4)

    with pytest.raises(ReferenceIOLimitError) as failure:
        AssetDiscoveryPlanner().scan((_record(),), roots, limits=tight)
    diagnostic = failure.value.to_dict()
    assert diagnostic["coverage_status"] == "incomplete"
    assert json.loads(failure.value.to_json()) == diagnostic
    assert diagnostic["effective_limits_id"] == tight.evidence_id

    match_limits = replace(
        ASSET_DISCOVERY_IO_LIMITS,
        max_match_evaluations=1,
    )
    with pytest.raises(ReferenceIOLimitError) as match_failure:
        AssetDiscoveryPlanner().scan(
            (_record("0"), _record("1")),
            roots,
            limits=match_limits,
        )
    assert match_failure.value.limit_name == "max_match_evaluations"

    acquisition_limits = replace(ACQUISITION_IO_LIMITS, max_file_bytes=4)
    with pytest.raises(ReferenceIOLimitError) as acquisition_failure:
        create_acquisition_manifest(
            source_id="synthetic",
            rows=(_acquisition_row(),),
            roots=roots,
            limits=acquisition_limits,
        )
    assert acquisition_failure.value.coverage_status == "incomplete"


def test__acquisition__observes_duplicate_source_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "example2026.pdf").write_bytes(b"%PDF- fixture")
    roots = (SearchRoot("staging", source, RootStorageClass.LOCAL),)
    observations = 0
    original = AuthorizedRoot.observe_file

    def counted(
        self: AuthorizedRoot,
        relative: object,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        nonlocal observations
        observations += 1
        return original(self, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(AuthorizedRoot, "observe_file", counted)
    duplicate = {
        **_acquisition_row(),
        "proposed_citekey": "other2026",
    }
    with pytest.raises(ValueError, match="duplicates an earlier source"):
        create_acquisition_manifest(
            source_id="synthetic",
            rows=(_acquisition_row(), duplicate),
            roots=roots,
        )
    assert observations == 1


def test__bibliography_nesting__includes_braces_inside_quotes(
    tmp_path: Path,
) -> None:
    depth = 129
    bibliography = tmp_path / "nested.bib"
    bibliography.write_text(
        '@article{example2026,title="'
        + "{" * depth
        + "x"
        + "}" * depth
        + '"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ReferenceIOLimitError) as caught:
        load_bibliography(bibliography, source_id="synthetic")
    assert caught.value.limit_name == "max_nesting_depth"
    assert caught.value.coverage_status == "incomplete"


def test__package_limits__retain_incomplete_coverage_status() -> None:
    nested = "[" * 65 + "0" + "]" * 65
    with pytest.raises(ReconciliationPackageLimitError) as caught:
        ReconciliationPackageManifest.from_json(nested)
    assert caught.value.coverage_status == "incomplete"
    assert caught.value.limit_name == "max_json_depth"
    assert caught.value.limits.evidence_id.startswith(
        "reference-io-limits:sha256:"
    )


def test__json_limits__reject_nesting_before_manifest_construction() -> None:
    limits = replace(ACQUISITION_IO_LIMITS, max_json_depth=3)
    with pytest.raises(ReferenceIOLimitError) as failure:
        AcquisitionManifest.from_json("[[[[0]]]]", limits=limits)
    assert failure.value.limit_name == "max_json_depth"
    assert failure.value.coverage_status == "incomplete"


def test__graph_limit_diagnostic_and_success_evidence(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources.csv"
    candidates = tmp_path / "candidates.csv"
    edges = tmp_path / "edges.csv"
    sources.write_text(
        "source_observation_id,source_id,asserted_source_revision,"
        "source_path,source_sha256,source_byte_size\n",
        encoding="utf-8",
    )
    candidates.write_text(
        "candidate_id,source_observation_id,source_locator,verbatim_entry,"
        "verbatim_identifier,verbatim_title,verbatim_authors,"
        "proposed_citekey,proposed_container_or_type,proposed_title,"
        "proposed_authors_json,proposed_year,proposed_doi\n",
        encoding="utf-8",
    )
    edges.write_text(
        "edge_id,source_observation_id,target_candidate_id,relation,"
        "source_locator\n",
        encoding="utf-8",
    )
    limits = GraphImportLimits(max_total_bytes=10)
    with pytest.raises(CitationGraphLimitError) as failure:
        load_candidate_graph(sources, candidates, edges, limits=limits)
    assert failure.value.to_dict()["coverage_status"] == "incomplete"
    assert failure.value.to_dict()["effective_limits_id"] == limits.evidence_id

    graph = load_candidate_graph(sources, candidates, edges)
    payload = json.loads(graph.to_json())
    assert payload["coverage_status"] == "complete"
    assert payload["effective_limits_id"] == graph.effective_limits.evidence_id


def test__over_count_csv__does_not_publish_manifest(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata.csv"
    row = _acquisition_row()
    with metadata.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerows(row for _ in range(257))
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "manifest.json"

    with pytest.raises(ReferenceIOLimitError) as failure:
        main(
            [
                "acquisition-create",
                str(metadata),
                str(output),
                "--source-id",
                "synthetic",
                "--metadata-storage-class",
                "local",
                "--output-storage-class",
                "local",
                "--source-root",
                f"local:staging={source}",
            ]
        )
    assert failure.value.limit_name == "max_rows"
    assert failure.value.coverage_status == "incomplete"
    assert not output.exists()


def test__oversized_bibliography__does_not_initialize_catalog(
    tmp_path: Path,
) -> None:
    bibliography = tmp_path / "oversized.bib"
    with bibliography.open("wb") as stream:
        stream.truncate(50_000_001)
    catalog = tmp_path / "catalog.sqlite3"

    with pytest.raises(ReferenceIOLimitError) as failure:
        main(
            [
                "bib-import",
                str(catalog),
                str(bibliography),
                "--source-id",
                "synthetic",
                "--catalog-storage-class",
                "local",
                "--bibliography-storage-class",
                "local",
            ]
        )
    assert failure.value.coverage_status == "incomplete"
    assert not catalog.exists()


class _NestedTransport:
    def get(self, request: TransportRequest) -> TransportResponse:
        del request
        return TransportResponse(
            body=b'{"status":"ok","message":{"nested":[[[[0]]]]}}',
            retrieved_at="2026-01-01T00:00:00+00:00",
        )


def test__provider_json_nesting__fails_before_cache_publication(
    tmp_path: Path,
) -> None:
    limits = replace(METADATA_IO_LIMITS, max_json_depth=3)
    cache = tmp_path / "cache"
    client = CrossrefClient(
        cache_directory=cache,
        transport=_NestedTransport(),
        limits=limits,
    )
    with pytest.raises(ProviderResponseError):
        client.fetch("10.1234/example")
    assert list(cache.rglob("*.json")) == []
