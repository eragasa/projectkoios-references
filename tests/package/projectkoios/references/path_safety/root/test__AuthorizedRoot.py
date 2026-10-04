from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path, PurePosixPath

import pytest
from projectkoios.references import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathSafetyError,
    PlaceholderPreflightError,
    PlaceholderProbeSupport,
    PlaceholderStatus,
    RootStorageClass,
)
from projectkoios.references.path_safety import platform as path_safety_platform


class OrdinaryFileProbe(CloudPlaceholderProbe):
    """Report ordinary metadata without granting byte-read authority."""

    __slots__ = ()

    probe_id = "ordinary-file-test-probe-v1"

    def support(self, *, root_alias: str) -> PlaceholderProbeSupport:
        del root_alias
        return PlaceholderProbeSupport.SUPPORTED

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        del root_alias, relative_path
        return PlaceholderStatus.ORDINARY_FILE


def test__authorized_write__is_create_only_and_does_not_follow_symlink(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="write root",
        root_alias="write-root",
        storage_class=RootStorageClass.LOCAL,
    )
    written = root.write_bytes("result.txt", b"first", replace=False)
    assert written.read_bytes() == b"first"
    with pytest.raises(FileExistsError):
        root.write_bytes("result.txt", b"second", replace=False)

    written.unlink()
    protected = tmp_path / "protected.txt"
    protected.write_bytes(b"protected")
    os.symlink(protected, written)
    with pytest.raises(PathSafetyError, match="replacement is disabled"):
        root.write_bytes("result.txt", b"replacement", replace=True)
    assert protected.read_bytes() == b"protected"


def test__write_bytes__publishes_from_an_unlinked_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )
    publish = (
        path_safety_platform.DescriptorFilesystem.publish_open_file_no_replace
    )
    observed = False

    def inspect_anonymous_source(
        *, parent: int, descriptor: int, destination: str
    ) -> None:
        nonlocal observed
        observed = True
        assert os.fstat(descriptor).st_nlink == 0
        assert not any(
            name.startswith(".koios-file-") for name in os.listdir(parent)
        )
        publish(
            parent=parent,
            descriptor=descriptor,
            destination=destination,
        )

    def forbidden_path_publication(
        *args: object,
        **kwargs: object,
    ) -> None:
        del args, kwargs
        raise AssertionError("publication used a mutable source pathname")

    monkeypatch.setattr(
        path_safety_platform.DescriptorFilesystem,
        "publish_open_file_no_replace",
        staticmethod(inspect_anonymous_source),
    )
    monkeypatch.setattr(os, "link", forbidden_path_publication)
    monkeypatch.setattr(os, "replace", forbidden_path_publication)

    published = root.write_bytes("payload", b"authorized", replace=False)

    assert observed
    assert published.read_bytes() == b"authorized"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS staging race")
def test__write_bytes__rejects_staging_inode_preserved_by_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )
    original_unlink = os.unlink
    raced = False

    def preserve_staging_inode(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal raced
        if (
            not raced
            and isinstance(path, str)
            and path.startswith(".koios-file-")
            and isinstance(kwargs.get("dir_fd"), int)
        ):
            directory = kwargs["dir_fd"]
            assert isinstance(directory, int)
            os.rename(
                path,
                "preserved-staging-inode",
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            replacement = os.open(
                path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory,
            )
            os.close(replacement)
            raced = True
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", preserve_staging_inode)

    with pytest.raises(PathSafetyError, match="staging is not anonymous"):
        root.write_bytes("payload", b"sensitive", replace=False)

    assert raced
    assert not (root_path / "payload").exists()
    assert (root_path / "preserved-staging-inode").read_bytes() == b""


def test__copy_file__closes_source_parent_when_destination_binding_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source"
    destination_path = tmp_path / "destination"
    source_path.mkdir()
    destination_path.mkdir()
    content = b"source"
    (source_path / "source.pdf").write_bytes(content)
    source = AuthorizedRoot.existing(
        source_path,
        label="source root",
        root_alias="source-root",
        storage_class=RootStorageClass.LOCAL,
    )
    destination = AuthorizedRoot.existing(
        destination_path,
        label="destination root",
        root_alias="destination-root",
        storage_class=RootStorageClass.LOCAL,
    )
    original_open_parent = AuthorizedRoot._open_parent

    def fail_destination_binding(
        self: AuthorizedRoot,
        parts: tuple[str, ...],
    ) -> int:
        if self is destination:
            raise PathSafetyError("synthetic destination binding failure")
        return original_open_parent(self, parts)

    monkeypatch.setattr(
        AuthorizedRoot,
        "_open_parent",
        fail_destination_binding,
    )
    descriptor_directory = (
        Path("/dev/fd") if Path("/dev/fd").is_dir() else Path("/proc/self/fd")
    )
    before = len(tuple(descriptor_directory.iterdir()))

    for _ in range(20):
        with pytest.raises(PathSafetyError, match="destination binding"):
            destination.copy_file_from(
                source,
                "source.pdf",
                "destination.pdf",
                max_bytes=100,
                expected_sha256=hashlib.sha256(content).hexdigest(),
                expected_size=len(content),
            )

    after = len(tuple(descriptor_directory.iterdir()))
    assert after == before


def test__create_directory__never_binds_replacement_after_atomic_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )
    rename = (
        path_safety_platform.DescriptorFilesystem._rename_directory_no_replace
    )

    def replace_after_claim(
        *, parent: int, source: str, destination: str
    ) -> None:
        rename(parent=parent, source=source, destination=destination)
        os.rename(
            destination,
            "claimed-original",
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )
        os.mkdir(destination, mode=0o700, dir_fd=parent)
        descriptor = os.open(
            destination,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            dir_fd=parent,
        )
        try:
            marker = os.open(
                "attacker-marker",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=descriptor,
            )
            os.close(marker)
        finally:
            os.close(descriptor)

    monkeypatch.setattr(
        path_safety_platform.DescriptorFilesystem,
        "_rename_directory_no_replace",
        staticmethod(replace_after_claim),
    )
    claimed = root.create_directory("publication")

    with pytest.raises(PathSafetyError, match="changed"):
        claimed.write_bytes("payload", b"bytes", replace=False)
    assert (root_path / "publication" / "attacker-marker").is_file()
    assert not (root_path / "publication" / "payload").exists()


def test__authorized_root__rejects_leaf_and_directory_symlink_swaps(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("safe", encoding="utf-8")
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )

    (root_path / "evidence.txt").unlink()
    (root_path / "evidence.txt").symlink_to(outside / "secret.txt")
    with pytest.raises(PathSafetyError):
        root.read_bytes("evidence.txt")

    (root_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathSafetyError):
        root.read_bytes("linked/secret.txt")


def test__authorized_root__rename_child_is_disabled_before_rename_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "source").mkdir()
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )
    invoked = False

    def forbidden_rename(*args: object, **kwargs: object) -> None:
        nonlocal invoked
        del args, kwargs
        invoked = True
        raise AssertionError("disabled rename_child invoked os.rename")

    monkeypatch.setattr(
        os,
        "rename",
        forbidden_rename,
    )
    with pytest.raises(PathSafetyError, match="disabled"):
        root.rename_child("source", "destination")

    assert not invoked
    assert (root_path / "source").is_dir()
    assert not (root_path / "destination").exists()


def test__authorized_root__rejects_symlink_introduced_during_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intended = tmp_path / "intended"
    intended.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = os.open
    swapped = False

    def swap_before_final_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal swapped
        if path == "intended" and kwargs.get("dir_fd") is not None:
            intended.rename(tmp_path / "original-intended")
            intended.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_final_open)

    with pytest.raises(PathSafetyError, match="cannot safely traverse"):
        AuthorizedRoot.existing(
            intended,
            label="intended root",
            root_alias="intended-root",
            storage_class=RootStorageClass.LOCAL,
        )

    assert swapped
    assert tuple(outside.iterdir()) == ()


def test__authorized_root__detects_root_replacement_before_read(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("original", encoding="utf-8")
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )

    root_path.rename(tmp_path / "original-root")
    root_path.mkdir()
    (root_path / "evidence.txt").write_text("replacement", encoding="utf-8")

    with pytest.raises(PathSafetyError, match="changed"):
        root.read_bytes("evidence.txt")


def test__mount_identity_mismatch__fails_before_leaf_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "target.pdf").write_bytes(b"bytes")
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )
    object.__setattr__(root, "mount_id", 1)

    def mismatched_mount_identity(*, descriptor: int) -> int:
        del descriptor
        return 2

    monkeypatch.setattr(
        path_safety_platform.DescriptorFilesystem,
        "mount_identity",
        staticmethod(mismatched_mount_identity),
    )

    descriptor_directory = (
        Path("/dev/fd") if Path("/dev/fd").is_dir() else Path("/proc/self/fd")
    )
    before = len(tuple(descriptor_directory.iterdir()))
    for _ in range(20):
        with pytest.raises(PlaceholderPreflightError) as caught:
            root.read_bytes("target.pdf")
        assert (
            caught.value.observation.status
            is PlaceholderStatus.FILESYSTEM_BOUNDARY
        )
    after = len(tuple(descriptor_directory.iterdir()))

    assert after == before


def test__exact_rollback__fails_closed_without_deleting(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root"
    root_path.mkdir()
    content = b"preserve"
    target = root_path / "target.pdf"
    target.write_bytes(content)
    root = AuthorizedRoot.existing(
        root_path,
        label="fixture root",
        root_alias="fixture-root",
        storage_class=RootStorageClass.LOCAL,
    )

    with pytest.raises(PathSafetyError, match="exact rollback is disabled"):
        root.remove_file_if_exact(
            "target.pdf",
            expected_sha256=hashlib.sha256(content).hexdigest(),
            expected_size=len(content),
            max_bytes=100,
        )

    assert target.read_bytes() == content


def test__authorized_root_create__rejects_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        PathSafetyError,
        match="cannot safely create or traverse publication parent: alias",
    ):
        AuthorizedRoot.create(
            alias / "new-parent",
            label="publication parent",
            root_alias="publication-parent",
            storage_class=RootStorageClass.LOCAL,
        )

    assert tuple(outside.iterdir()) == ()


def test__cloud_ordinary_file__remains_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "cloud"
    root_path.mkdir()
    (root_path / "ordinary.pdf").write_bytes(b"bytes")
    root = AuthorizedRoot.existing(
        root_path,
        label="synthetic cloud root",
        root_alias="synthetic-cloud",
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=OrdinaryFileProbe(),
    )
    opened: list[object] = []
    original_open = os.open

    def recording_open(path: object, *args: object, **kwargs: object) -> int:
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    with pytest.raises(PlaceholderPreflightError) as caught:
        root.read_bytes("ordinary.pdf")

    assert (
        caught.value.observation.status is PlaceholderStatus.ACCESS_CONTROLLED
    )
    assert "ordinary.pdf" not in opened
