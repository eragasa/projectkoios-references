from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from projectkoios.references import (
    PDF_CORPUS_DISCOVERY_ARTIFACT_KIND,
    PDF_CORPUS_DISCOVERY_CONTRACT_ID,
    PDF_CORPUS_DISCOVERY_CONTRACT_STATUS,
    PDF_CORPUS_DISCOVERY_CONTRACT_VERSION,
    PDF_CORPUS_DISCOVERY_GENERATOR_NAME,
    PDF_CORPUS_DISCOVERY_GENERATOR_VERSION,
    PDF_CORPUS_DISCOVERY_IO_LIMITS,
    PDF_CORPUS_DISCOVERY_SCHEMA_VERSION,
    AuthorizedRoot,
    CloudPlaceholderProbe,
    MacOSFileProviderPlaceholderProbe,
    PdfCorpusDiscoveryPlan,
    PdfCorpusRoot,
    PdfSkipReason,
    PdfSourceObservation,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    ReferenceIOLimitError,
    RootStorageClass,
    discover_pdf_corpus,
    rebind_pdf_source,
)


class SyntheticProbe(CloudPlaceholderProbe):
    probe_id = "synthetic-pdf-corpus-probe-v1"

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


def test__pdf_corpus__canonical_privacy_reduced_replay_and_processable_view(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "private" / "papers"
    nested = root_path / "nested"
    nested.mkdir(parents=True)
    valid = b"%PDF-1.7\nsynthetic fixture"
    invalid = b"not actually a PDF"
    (nested / "b.PDF").write_bytes(valid)
    (root_path / "a.pdf").write_bytes(invalid)
    (root_path / "ignored.txt").write_text("ignored", encoding="utf-8")

    root = PdfCorpusRoot("papers", root_path, RootStorageClass.LOCAL)
    plan = discover_pdf_corpus((root,))

    assert plan.schema_version == PDF_CORPUS_DISCOVERY_SCHEMA_VERSION
    assert plan.artifact_kind == PDF_CORPUS_DISCOVERY_ARTIFACT_KIND
    assert plan.contract_id == PDF_CORPUS_DISCOVERY_CONTRACT_ID
    assert plan.contract_version == PDF_CORPUS_DISCOVERY_CONTRACT_VERSION
    assert plan.contract_status == PDF_CORPUS_DISCOVERY_CONTRACT_STATUS
    assert plan.generator_name == PDF_CORPUS_DISCOVERY_GENERATOR_NAME
    assert plan.generator_version == PDF_CORPUS_DISCOVERY_GENERATOR_VERSION
    assert plan.coverage_status == "complete"
    assert tuple(item.relative_path for item in plan.source_observations) == (
        "a.pdf",
        "nested/b.PDF",
    )
    assert tuple(item.relative_path for item in plan.processable_sources) == (
        "nested/b.PDF",
    )
    invalid_observation, valid_observation = plan.source_observations
    assert invalid_observation.pdf_header_valid is False
    assert valid_observation.pdf_header_valid is True
    assert valid_observation.byte_size == len(valid)
    assert valid_observation.sha256 == hashlib.sha256(valid).hexdigest()
    assert valid_observation.content_id == (
        f"blob:sha256:{hashlib.sha256(valid).hexdigest()}"
    )
    assert valid_observation.observation_id.startswith(
        "pdf-source-observation:sha256:"
    )
    assert plan.plan_id.startswith("pdf-corpus-discovery-plan:sha256:")
    assert str(tmp_path) not in plan.to_json()
    assert "root_path" not in plan.to_json()
    assert PdfCorpusDiscoveryPlan.from_json(plan.to_json()) == plan

    second = discover_pdf_corpus((root,))
    assert second.to_json() == plan.to_json()
    assert second.plan_id == plan.plan_id


def test__pdf_corpus__retains_symlink_unsupported_and_missing_root(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "objects"
    root_path.mkdir()
    (root_path / "ordinary.pdf").write_bytes(b"%PDF- ordinary")
    (root_path / "target.pdf").write_bytes(b"%PDF- target")
    (root_path / "linked.pdf").symlink_to("target.pdf")
    unreadable = root_path / "unreadable.pdf"
    unreadable.write_bytes(b"%PDF- unreadable")
    unreadable.chmod(0)
    fifo = root_path / "special.pdf"
    os.mkfifo(fifo)

    plan = discover_pdf_corpus(
        (
            PdfCorpusRoot("objects", root_path, RootStorageClass.LOCAL),
            PdfCorpusRoot(
                "missing",
                tmp_path / "missing",
                RootStorageClass.LOCAL,
            ),
        )
    )

    assert plan.coverage_status == "incomplete"
    assert {item.relative_path for item in plan.source_observations} == {
        "ordinary.pdf",
        "target.pdf",
    }
    assert {
        (item.root_alias, item.relative_path, item.reason)
        for item in plan.skipped_observations
    } == {
        ("missing", None, PdfSkipReason.ROOT_MISSING),
        ("objects", "linked.pdf", PdfSkipReason.SYMLINK),
        ("objects", "special.pdf", PdfSkipReason.UNSUPPORTED_OBJECT),
        ("objects", "unreadable.pdf", PdfSkipReason.UNREADABLE),
    }
    assert str(tmp_path) not in plan.to_json()


def test__pdf_corpus__overlapping_roots_fail_before_path_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    child = parent / "cloud"
    child.mkdir(parents=True)
    probe = SyntheticProbe()
    touched = False

    def forbidden_stat(*args: object, **kwargs: object) -> object:
        nonlocal touched
        del args, kwargs
        touched = True
        raise AssertionError("overlapping roots reached filesystem access")

    monkeypatch.setattr(
        "projectkoios.references.pdf_corpus.os.stat", forbidden_stat
    )
    with pytest.raises(ValueError, match="duplicate or overlap"):
        discover_pdf_corpus(
            (
                PdfCorpusRoot("local", parent, RootStorageClass.LOCAL),
                PdfCorpusRoot(
                    "cloud",
                    child,
                    RootStorageClass.CLOUD_BACKED,
                    probe,
                ),
            )
        )
    with pytest.raises(ValueError, match="duplicate or overlap"):
        discover_pdf_corpus(
            (
                PdfCorpusRoot("first", parent, RootStorageClass.LOCAL),
                PdfCorpusRoot("second", parent, RootStorageClass.LOCAL),
            )
        )

    assert not touched
    assert probe.calls == []


def test__pdf_corpus__rejects_root_with_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    physical = tmp_path / "physical"
    child = physical / "child"
    child.mkdir(parents=True)
    alias_parent = tmp_path / "aliases"
    alias_parent.mkdir()
    (alias_parent / "physical-link").symlink_to(
        physical,
        target_is_directory=True,
    )
    alias_child = alias_parent / "physical-link" / "child"

    plan = discover_pdf_corpus(
        (
            PdfCorpusRoot("physical", physical, RootStorageClass.LOCAL),
            PdfCorpusRoot("alias-child", alias_child, RootStorageClass.LOCAL),
        )
    )

    assert plan.source_observations == ()
    assert any(
        item.root_alias == "alias-child"
        and item.reason is PdfSkipReason.UNSAFE_ROOT
        for item in plan.skipped_observations
    )


def test__pdf_corpus__filesystem_boundary_is_typed_and_not_descended(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mounted = tmp_path / "mounted"
    mounted.mkdir()
    (mounted / "inside.pdf").write_bytes(b"%PDF- must not be read")
    (tmp_path / "outside.pdf").write_bytes(b"%PDF- ordinary")
    mounted_inode = mounted.stat().st_ino
    real_fstat = os.fstat
    observed: list[str] = []
    original_observe = AuthorizedRoot.observe_file

    def synthetic_device(descriptor: int) -> object:
        metadata = real_fstat(descriptor)
        if metadata.st_ino == mounted_inode and stat.S_ISDIR(metadata.st_mode):
            return SimpleNamespace(st_dev=metadata.st_dev + 1)
        return metadata

    def counted_observe(
        self: AuthorizedRoot,
        relative: str | PurePosixPath,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        observed.append(str(relative))
        return original_observe(self, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        os,
        "fstat",
        synthetic_device,
    )
    monkeypatch.setattr(AuthorizedRoot, "observe_file", counted_observe)
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )

    assert tuple(item.relative_path for item in plan.source_observations) == (
        "outside.pdf",
    )
    assert observed == ["outside.pdf"]
    assert any(
        item.relative_path == "mounted"
        and item.reason is PdfSkipReason.FILESYSTEM_BOUNDARY
        for item in plan.skipped_observations
    )
    assert plan.coverage_status == "incomplete"


def test__pdf_corpus__post_inventory_device_change_is_typed_before_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "source.pdf").write_bytes(b"%PDF- must not be read")
    nested_inode = nested.stat().st_ino
    real_fstat = os.fstat
    original_inventory = AuthorizedRoot.inventory_files
    inventory_complete = False

    def changing_inventory(
        self: AuthorizedRoot,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        nonlocal inventory_complete
        result = original_inventory(self, **kwargs)  # type: ignore[arg-type]
        inventory_complete = True
        return result

    def changed_device(descriptor: int) -> object:
        metadata = real_fstat(descriptor)
        if inventory_complete and metadata.st_ino == nested_inode:
            return SimpleNamespace(st_dev=metadata.st_dev + 1)
        return metadata

    def forbidden_observe(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("post-inventory mount reached candidate bytes")

    monkeypatch.setattr(AuthorizedRoot, "inventory_files", changing_inventory)
    monkeypatch.setattr(
        os,
        "fstat",
        changed_device,
    )
    monkeypatch.setattr(AuthorizedRoot, "observe_file", forbidden_observe)
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )

    assert plan.source_observations == ()
    assert any(
        item.relative_path == "nested/source.pdf"
        and item.reason is PdfSkipReason.FILESYSTEM_BOUNDARY
        for item in plan.skipped_observations
    )


def test__pdf_corpus__mounted_leaf_is_typed_before_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "mounted.pdf").write_bytes(b"%PDF- must not be read")
    real_stat = os.stat

    def mounted_leaf(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        metadata = real_stat(path, *args, **kwargs)  # type: ignore[arg-type]
        if path == "mounted.pdf" and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(st_dev=metadata.st_dev + 1)
        return metadata

    def forbidden_observe(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("mounted leaf reached candidate bytes")

    monkeypatch.setattr(
        os,
        "stat",
        mounted_leaf,
    )
    monkeypatch.setattr(AuthorizedRoot, "observe_file", forbidden_observe)
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )

    assert plan.source_observations == ()
    assert plan.skipped_observations[0].reason is (
        PdfSkipReason.FILESYSTEM_BOUNDARY
    )


def test__pdf_corpus__cloud_preflights_every_candidate_before_byte_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "cloud"
    root_path.mkdir()
    (root_path / "ordinary.pdf").write_bytes(b"%PDF- ordinary")
    (root_path / "placeholder.pdf").write_bytes(b"placeholder stub")
    probe = SyntheticProbe(
        {"placeholder.pdf": PlaceholderStatus.CLOUD_PLACEHOLDER}
    )
    observed: list[str] = []
    original = AuthorizedRoot.observe_file

    def counted(
        self: AuthorizedRoot,
        relative: str | PurePosixPath,
        **kwargs: object,
    ):  # type: ignore[no-untyped-def]
        observed.append(str(relative))
        return original(self, relative, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(AuthorizedRoot, "observe_file", counted)
    plan = discover_pdf_corpus(
        (
            PdfCorpusRoot(
                "icloud",
                root_path,
                RootStorageClass.CLOUD_BACKED,
                probe,
            ),
        )
    )

    assert plan.source_observations == ()
    assert observed == ["ordinary.pdf"]
    assert {
        (item.relative_path, item.reason) for item in plan.skipped_observations
    } == {
        ("ordinary.pdf", PdfSkipReason.ACCESS_CONTROLLED),
        ("placeholder.pdf", PdfSkipReason.CLOUD_PLACEHOLDER),
    }
    candidate_calls = {
        relative for _alias, relative in probe.calls if relative is not None
    }
    assert candidate_calls == {"ordinary.pdf", "placeholder.pdf"}
    assert plan.coverage_status == "incomplete"


def test__pdf_corpus__unsupported_cloud_root_never_touches_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SyntheticProbe(support=PlaceholderProbeSupport.UNSUPPORTED_PLATFORM)
    touched = False

    def forbidden_stat(*args: object, **kwargs: object) -> object:
        nonlocal touched
        del args, kwargs
        touched = True
        raise AssertionError("unsupported root reached filesystem metadata")

    monkeypatch.setattr(
        "projectkoios.references.pdf_corpus.os.stat", forbidden_stat
    )
    plan = discover_pdf_corpus(
        (
            PdfCorpusRoot(
                "cloud",
                tmp_path / "not-touched",
                RootStorageClass.CLOUD_BACKED,
                probe,
            ),
        )
    )

    assert not touched
    assert plan.coverage_status == "incomplete"
    assert plan.skipped_observations[0].reason is (
        PdfSkipReason.UNSUPPORTED_PLATFORM
    )
    assert plan.root_preflights[0].probe_support is (
        PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
    )


def test__pdf_corpus__limits_are_retained_not_interpreted_as_absence(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "limited"
    root_path.mkdir()
    (root_path / "a.pdf").write_bytes(b"%PDF- a")
    (root_path / "b.pdf").write_bytes(b"%PDF- b")
    limits = replace(PDF_CORPUS_DISCOVERY_IO_LIMITS, max_files=1)

    plan = discover_pdf_corpus(
        (PdfCorpusRoot("limited", root_path, RootStorageClass.LOCAL),),
        limits=limits,
    )

    assert plan.coverage_status == "incomplete"
    assert plan.source_observations == ()
    limit = next(
        item
        for item in plan.skipped_observations
        if item.reason is PdfSkipReason.FILE_LIMIT
    )
    assert limit.limit_name == "max_files"
    assert limit.limit == 1
    assert limit.observed == 2
    assert (
        PdfCorpusDiscoveryPlan.from_json(plan.to_json(), limits=limits) == plan
    )


def test__pdf_corpus__strict_replay_rejects_tamper_and_noncanonical_json(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.pdf").write_bytes(b"%PDF- fixture")
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )
    value = json.loads(plan.to_json())
    value["source_observations"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="malformed"):
        PdfCorpusDiscoveryPlan.from_json(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )

    with pytest.raises(ValueError, match="noncanonical"):
        PdfCorpusDiscoveryPlan.from_json(
            json.dumps(json.loads(plan.to_json()), separators=(",", ":"))
        )

    value = json.loads(plan.to_json())
    value["absolute_root"] = str(tmp_path)
    with pytest.raises(ValueError, match="fields are invalid"):
        PdfCorpusDiscoveryPlan.from_json(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )


def test__pdf_corpus__strict_replay_enforces_recorded_source_depth(
    tmp_path: Path,
) -> None:
    content = b"%PDF- fixture"
    (tmp_path / "source.pdf").write_bytes(content)
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )
    original = plan.source_observations[0]
    deep = PdfSourceObservation.create(
        root_alias=original.root_alias,
        relative_path="one/two/source.pdf",
        storage_class=original.storage_class,
        probe_id=original.probe_id,
        sha256=original.sha256,
        byte_size=original.byte_size,
        pdf_header_valid=original.pdf_header_valid,
    )
    recorded = replace(plan.effective_limits, max_nesting_depth=1)
    value = json.loads(plan.to_json())
    value["effective_limits"] = recorded.to_dict()
    value["effective_limits_id"] = recorded.evidence_id
    value["source_observations"] = [asdict(deep)]
    canonical = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ValueError, match="recorded max_nesting_depth"):
        PdfCorpusDiscoveryPlan.from_json(canonical)


def test__pdf_corpus__strict_replay_enforces_recorded_skipped_text(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF- fixture")
    (tmp_path / "long-link.pdf").symlink_to("a.pdf")
    plan = discover_pdf_corpus(
        (PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL),)
    )
    recorded = replace(plan.effective_limits, max_text_bytes=8)
    value = json.loads(plan.to_json())
    value["effective_limits"] = recorded.to_dict()
    value["effective_limits_id"] = recorded.evidence_id
    canonical = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    with pytest.raises(ValueError, match="recorded max_text_bytes"):
        PdfCorpusDiscoveryPlan.from_json(canonical)


def test__cloud_pdf_source__requires_separate_hydration_authority(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "rebind"
    root_path.mkdir()
    (root_path / "source.pdf").write_bytes(b"%PDF- original")
    probe = SyntheticProbe()
    roots = (
        PdfCorpusRoot(
            "cloud",
            root_path,
            RootStorageClass.CLOUD_BACKED,
            probe,
        ),
    )

    plan = discover_pdf_corpus(roots)

    assert plan.processable_sources == ()
    assert plan.skipped_observations[0].reason is (
        PdfSkipReason.ACCESS_CONTROLLED
    )


@pytest.mark.parametrize(
    ("limit_kind", "expected_name"),
    (
        ("total", "max_total_bytes"),
        ("depth", "max_nesting_depth"),
        ("text", "max_text_bytes"),
    ),
)
def test__rebind_pdf_source__enforces_tightened_limits_before_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_kind: str,
    expected_name: str,
) -> None:
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    candidate = nested / "source.pdf"
    candidate.write_bytes(b"%PDF- bounded source")
    root = PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL)
    source = discover_pdf_corpus((root,)).processable_sources[0]
    if limit_kind == "total":
        limits = replace(
            PDF_CORPUS_DISCOVERY_IO_LIMITS,
            max_total_bytes=source.byte_size - 1,
        )
    elif limit_kind == "depth":
        limits = replace(
            PDF_CORPUS_DISCOVERY_IO_LIMITS,
            max_nesting_depth=1,
        )
    else:
        limits = replace(
            PDF_CORPUS_DISCOVERY_IO_LIMITS,
            max_text_bytes=len(source.relative_path.encode("utf-8")) - 1,
        )

    def forbidden_existing(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("tightened limit reached root reopen")

    monkeypatch.setattr(AuthorizedRoot, "existing", forbidden_existing)
    with pytest.raises(ReferenceIOLimitError) as caught:
        rebind_pdf_source(source, (root,), limits=limits)

    assert caught.value.limit_name == expected_name


def test__rebind_pdf_source__bounds_observation_by_total_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "source.pdf"
    original = b"%PDF- original"
    candidate.write_bytes(original)
    root = PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL)
    source = discover_pdf_corpus((root,)).processable_sources[0]
    limits = replace(
        PDF_CORPUS_DISCOVERY_IO_LIMITS,
        max_total_bytes=len(original),
    )
    candidate.write_bytes(original + b" changed")

    def forbidden_fdopen(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("over-total rebind read candidate bytes")

    monkeypatch.setattr(
        os,
        "fdopen",
        forbidden_fdopen,
    )
    with pytest.raises(ReferenceIOLimitError) as caught:
        rebind_pdf_source(source, (root,), limits=limits)

    assert caught.value.limit_name == "max_total_bytes"
    assert caught.value.observed == len(original + b" changed")


def test__rebind_pdf_source__fails_on_cross_device_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    candidate = nested / "source.pdf"
    candidate.write_bytes(b"%PDF- source")
    root = PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL)
    source = discover_pdf_corpus((root,)).processable_sources[0]
    nested_inode = nested.stat().st_ino
    real_fstat = os.fstat

    def mounted_parent(descriptor: int) -> object:
        metadata = real_fstat(descriptor)
        if metadata.st_ino == nested_inode:
            return SimpleNamespace(st_dev=metadata.st_dev + 1)
        return metadata

    monkeypatch.setattr(
        os,
        "fstat",
        mounted_parent,
    )
    with pytest.raises(PlaceholderPreflightError) as caught:
        rebind_pdf_source(source, (root,))

    assert caught.value.observation.status is (
        PlaceholderStatus.FILESYSTEM_BOUNDARY
    )


def test__rebind_pdf_source__rejects_overlapping_roots_before_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "source.pdf").write_bytes(b"%PDF- source")
    root = PdfCorpusRoot("root", tmp_path, RootStorageClass.LOCAL)
    source = discover_pdf_corpus((root,)).processable_sources[0]
    nested = tmp_path / "nested"
    nested.mkdir()

    def forbidden_existing(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("overlapping rebind roots reached path access")

    monkeypatch.setattr(AuthorizedRoot, "existing", forbidden_existing)
    with pytest.raises(ValueError, match="duplicate or overlap"):
        rebind_pdf_source(
            source,
            (
                root,
                PdfCorpusRoot("nested", nested, RootStorageClass.LOCAL),
            ),
        )


def test__macos_file_provider_probe__root_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    declared = tmp_path / "declared"
    captured = tmp_path / "captured"
    declared.mkdir()
    captured.mkdir()
    probe = MacOSFileProviderPlaceholderProbe(captured)

    with pytest.raises(ValueError, match="different root"):
        PdfCorpusRoot(
            "icloud",
            declared,
            RootStorageClass.CLOUD_BACKED,
            probe,
        )


def test__macos_file_provider_probe__rejects_cross_device_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
        pytest.skip("macOS SF_DATALESS metadata is unavailable")
    child = tmp_path / "child"
    child.mkdir()
    (child / "candidate.pdf").write_bytes(b"must not be inspected")
    child_inode = child.stat().st_ino
    probe = MacOSFileProviderPlaceholderProbe(tmp_path)
    AuthorizedRoot.existing(
        tmp_path,
        label="synthetic iCloud root",
        root_alias="icloud",
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=probe,
    )
    real_fstat = os.fstat
    real_stat = os.stat

    def mounted_parent(descriptor: int) -> object:
        metadata = real_fstat(descriptor)
        if metadata.st_ino == child_inode:
            return SimpleNamespace(st_dev=metadata.st_dev + 1)
        return metadata

    def forbidden_leaf_stat(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        if path == "candidate.pdf":
            raise AssertionError("probe crossed device boundary")
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        os,
        "fstat",
        mounted_parent,
    )
    monkeypatch.setattr(
        os,
        "stat",
        forbidden_leaf_stat,
    )

    assert (
        probe.observe(
            root_alias="icloud",
            relative_path=PurePosixPath("child/candidate.pdf"),
        )
        is PlaceholderStatus.FILESYSTEM_BOUNDARY
    )


def test__macos_file_provider_probe__uses_nofollow_metadata_not_leaf_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
        pytest.skip("macOS SF_DATALESS metadata is unavailable")
    sf_dataless = getattr(stat, "SF_DATALESS")  # noqa: B009
    candidate = tmp_path / "candidate.pdf"
    candidate.write_bytes(b"placeholder bytes must not be read")
    probe = MacOSFileProviderPlaceholderProbe(tmp_path)
    AuthorizedRoot.existing(
        tmp_path,
        label="synthetic iCloud root",
        root_alias="icloud",
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=probe,
    )
    real_stat = os.stat
    real_open = os.open
    dataless = True
    stat_calls: list[tuple[object, bool]] = []
    open_calls: list[tuple[object, int]] = []

    def metadata_stat(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        result = real_stat(path, *args, **kwargs)  # type: ignore[arg-type]
        follow = kwargs.get("follow_symlinks", True)
        stat_calls.append((path, bool(follow)))
        if path == "candidate.pdf" and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(
                st_dev=result.st_dev,
                st_mode=result.st_mode,
                st_flags=sf_dataless if dataless else 0,
            )
        return result

    def directory_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        open_calls.append((path, flags))
        if path == "candidate.pdf":
            raise AssertionError("probe opened candidate bytes")
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "stat", metadata_stat)
    monkeypatch.setattr(os, "open", directory_open)

    assert (
        probe.support(root_alias="icloud") is PlaceholderProbeSupport.SUPPORTED
    )
    assert (
        probe.observe(
            root_alias="icloud",
            relative_path=PurePosixPath("candidate.pdf"),
        )
        is PlaceholderStatus.CLOUD_PLACEHOLDER
    )
    dataless = False
    assert (
        probe.observe(
            root_alias="icloud",
            relative_path=PurePosixPath("candidate.pdf"),
        )
        is PlaceholderStatus.ORDINARY_FILE
    )
    assert ("candidate.pdf", False) in stat_calls
    assert all(
        flags & getattr(os, "O_DIRECTORY", 0) for _path, flags in open_calls
    )


def test__macos_file_provider_probe__uncertain_leaf_is_ambiguous(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"):
        pytest.skip("macOS SF_DATALESS metadata is unavailable")
    target = tmp_path / "target.pdf"
    target.write_bytes(b"%PDF- target")
    (tmp_path / "linked.pdf").symlink_to(target)
    probe = MacOSFileProviderPlaceholderProbe(tmp_path)
    AuthorizedRoot.existing(
        tmp_path,
        label="synthetic iCloud root",
        root_alias="icloud",
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=probe,
    )

    assert (
        probe.observe(
            root_alias="icloud",
            relative_path=PurePosixPath("linked.pdf"),
        )
        is PlaceholderStatus.AMBIGUOUS
    )
