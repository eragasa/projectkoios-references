"""Composed create-only filesystem publication capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO, final

from projectkoios.references.filesystem.observation.capability import (
    RootObservation,
)
from projectkoios.references.filesystem.publication.copy.action import (
    VerifiedFileCopier,
)
from projectkoios.references.filesystem.publication.directory.action import (
    DirectoryPublisher,
)
from projectkoios.references.filesystem.publication.result import (
    AddressedFilePublication,
)
from projectkoios.references.filesystem.publication.staging.action import (
    AnonymousFilePublisher,
)
from projectkoios.references.filesystem.publication.verification.action import (
    PublishedFileVerifier,
)
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.root.identity import (
    AuthorizedRootIdentity,
)


@final
@dataclass(frozen=True, slots=True, eq=False)
class RootPublication:
    """Compose narrow create-only publication operations."""

    _descriptor: RootDescriptor
    _directories: DirectoryPublisher = field(init=False, repr=False)
    _files: AnonymousFilePublisher = field(init=False, repr=False)
    _copier: VerifiedFileCopier = field(init=False, repr=False)

    def __post_init__(self) -> None:
        verifier = PublishedFileVerifier(self._descriptor)
        object.__setattr__(
            self,
            "_directories",
            DirectoryPublisher(self._descriptor),
        )
        object.__setattr__(
            self,
            "_files",
            AnonymousFilePublisher(self._descriptor, verifier),
        )
        object.__setattr__(
            self,
            "_copier",
            VerifiedFileCopier(self._descriptor, verifier),
        )

    def create_directory(
        self, relative: str | PurePosixPath
    ) -> AuthorizedRootIdentity:
        return self._directories.create_directory(relative)

    def create_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
    ) -> Path:
        return self._files.create_bytes(relative, content)

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
        return self._files.publish_addressed_stream(
            stream,
            suffix=suffix,
            max_bytes=max_bytes,
            required_prefix=required_prefix,
            expected_size=expected_size,
            chunk_bytes=chunk_bytes,
        )

    def copy_file_from(
        self,
        source_root: RootObservation,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
        *,
        max_bytes: int,
        expected_sha256: str,
        expected_size: int,
        chunk_bytes: int = 1_048_576,
    ) -> Path:
        return self._copier.copy_file_from(
            source_root,
            source,
            destination,
            max_bytes=max_bytes,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            chunk_bytes=chunk_bytes,
        )
