from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal, Self, final

from projectkoios.references.filesystem.inventory.result import (
    FilesystemInventory,
)
from projectkoios.references.filesystem.observation.capability import (
    RootObservation,
)
from projectkoios.references.filesystem.observation.file import FileObservation
from projectkoios.references.filesystem.publication.capability import (
    RootPublication,
)
from projectkoios.references.filesystem.publication.result import (
    AddressedFilePublication,
)
from projectkoios.references.filesystem.root.authorization.action import (
    authorize_existing_root,
    create_root_identity,
)
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)
from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)
from projectkoios.references.filesystem.root.preflight.observation import (
    PlaceholderObservation,
)
from projectkoios.references.filesystem.root.preflight.probe import (
    CloudPlaceholderProbe,
    RootPlaceholderProbe,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)
from projectkoios.references.filesystem.scanning.capability import RootScanning


@final
@dataclass(frozen=True, slots=True, eq=False)
class AuthorizedRoot:
    """One runtime root capability composed from narrow filesystem actions."""

    _identity: AuthorizedRootIdentity
    _placeholder_probe: CloudPlaceholderProbe | None
    _observation: RootObservation = field(init=False, repr=False)
    _scanning: RootScanning = field(init=False, repr=False)
    _publication: RootPublication = field(init=False, repr=False)

    def __post_init__(self) -> None:
        descriptor = RootDescriptor(self._identity)
        object.__setattr__(
            self,
            "_observation",
            RootObservation(descriptor, self._placeholder_probe),
        )
        object.__setattr__(self, "_scanning", RootScanning(descriptor))
        object.__setattr__(self, "_publication", RootPublication(descriptor))

    @property
    def identity(self) -> AuthorizedRootIdentity:
        return self._identity

    @property
    def placeholder_probe(self) -> CloudPlaceholderProbe | None:
        return self._placeholder_probe

    @property
    def observation(self) -> RootObservation:
        return self._observation

    @property
    def scanning(self) -> RootScanning:
        return self._scanning

    @property
    def publication(self) -> RootPublication:
        return self._publication

    @classmethod
    def existing(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: RootStorageClass,
        placeholder_probe: RootPlaceholderProbe | None = None,
    ) -> Self:
        identity, bound_probe = authorize_existing_root(
            path,
            label=label,
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        retained_probe = (
            bound_probe
            if storage_class is RootStorageClass.CLOUD_BACKED
            else None
        )
        return cls(identity, retained_probe)

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        label: str,
        root_alias: str,
        storage_class: RootStorageClass,
        placeholder_probe: RootPlaceholderProbe | None = None,
    ) -> Self:
        identity = create_root_identity(
            path,
            label=label,
            root_alias=root_alias,
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        return cls(identity, None)

    @property
    def path(self) -> Path:
        return self.identity.path

    @property
    def label(self) -> str:
        return self.identity.label

    @property
    def device(self) -> int:
        return self.identity.device

    @property
    def inode(self) -> int:
        return self.identity.inode

    @property
    def mount_id(self) -> int | None:
        return self.identity.mount_id

    @property
    def preflight_evidence(self) -> RootPreflightEvidence:
        return self.identity.preflight_evidence

    def child_path(self, relative: str | PurePosixPath) -> Path:
        return RootDescriptor(self.identity).child_path(relative)

    def state(
        self, relative: str | PurePosixPath
    ) -> Literal["missing", "regular", "directory"]:
        return self.observation.state(relative)

    def preflight_file(
        self, relative: str | PurePosixPath
    ) -> PlaceholderObservation:
        return self.observation.preflight_file(relative)

    def require_readable_file(
        self, relative: str | PurePosixPath
    ) -> PlaceholderObservation:
        return self.observation.require_readable_file(relative)

    def read_bytes(
        self, relative: str | PurePosixPath, *, max_bytes: int = 50_000_000
    ) -> bytes:
        return self.observation.read_bytes(relative, max_bytes=max_bytes)

    def read_text(
        self,
        relative: str | PurePosixPath,
        *,
        encoding: str = "utf-8",
        max_bytes: int = 50_000_000,
    ) -> str:
        return self.observation.read_text(
            relative, encoding=encoding, max_bytes=max_bytes
        )

    def observe_file(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int,
        prefix_bytes: int = 0,
        chunk_bytes: int = 1_048_576,
    ) -> FileObservation:
        return self.observation.observe_file(
            relative,
            max_bytes=max_bytes,
            prefix_bytes=prefix_bytes,
            chunk_bytes=chunk_bytes,
        )

    def iter_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        reject_directories: bool = False,
        max_files: int | None = None,
        max_entries: int | None = None,
        max_depth: int | None = None,
    ) -> tuple[PurePosixPath, ...]:
        return self.scanning.iter_files(
            suffix=suffix,
            recursive=recursive,
            reject_directories=reject_directories,
            max_files=max_files,
            max_entries=max_entries,
            max_depth=max_depth,
        )

    def inventory_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        max_files: int,
        max_entries: int,
        max_depth: int,
        case_sensitive_suffix: bool = True,
    ) -> FilesystemInventory:
        return self.scanning.inventory_files(
            suffix=suffix,
            recursive=recursive,
            max_files=max_files,
            max_entries=max_entries,
            max_depth=max_depth,
            case_sensitive_suffix=case_sensitive_suffix,
        )

    def create_directory(self, relative: str | PurePosixPath) -> Self:
        identity = self.publication.create_directory(relative)
        return type(self)(identity, self.placeholder_probe)

    def create_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
    ) -> Path:
        return self.publication.create_bytes(relative, content)

    def publish_addressed_stream(
        self,
        stream: BinaryIO,
        *,
        suffix: str,
        max_bytes: int,
        required_prefix: bytes = b"",
        expected_size: int | None = None,
        chunk_bytes: int = 1_048_576,
    ) -> AddressedFilePublication:
        return self.publication.publish_addressed_stream(
            stream,
            suffix=suffix,
            max_bytes=max_bytes,
            required_prefix=required_prefix,
            expected_size=expected_size,
            chunk_bytes=chunk_bytes,
        )

    def copy_file_from(
        self,
        source_root: AuthorizedRoot,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
        *,
        max_bytes: int,
        expected_sha256: str,
        expected_size: int,
        chunk_bytes: int = 1_048_576,
    ) -> Path:
        return self.publication.copy_file_from(
            source_root.observation,
            source,
            destination,
            max_bytes=max_bytes,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            chunk_bytes=chunk_bytes,
        )
