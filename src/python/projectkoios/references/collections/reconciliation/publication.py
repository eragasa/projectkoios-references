from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.io_limits import RECONCILIATION_PACKAGE_IO_LIMITS
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    CloudRootMutationError,
    PathLimitError,
    PathSafetyError,
    PlaceholderPreflightError,
    RootStorageClass,
    validate_relative_path,
)
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    LoadedReconciliationPackage,
    ReconciliationPackageError,
    ReconciliationPackageManifest,
    load_reconciliation_package,
    parse_package_files,
)

from ._contract import _limit_error, _required_limit
from .errors import (
    CollectionReconciliationError,
    IncompleteReconciliationPublicationError,
)
from .manifest import ReconciliationOutputs


@final
@dataclass(frozen=True)
class PublicationResult(DataObjectModel):
    status: str
    output_directory: Path
    package_id: str


def _verify_reconciliation_publication(
    directory: AuthorizedRoot, expected: dict[str, bytes]
) -> None:
    if directory.state(PACKAGE_MANIFEST_FILENAME) != "regular":
        raise IncompleteReconciliationPublicationError(
            "reconciliation output has no completion manifest"
        )
    directory_limit = min(
        _required_limit(
            RECONCILIATION_PACKAGE_IO_LIMITS.max_entries, "max_entries"
        ),
        len(expected) + 1,
    )
    actual_names = {
        path.name
        for path in directory.iter_files(
            suffix="",
            recursive=False,
            reject_directories=True,
            max_files=directory_limit,
            max_entries=directory_limit,
            max_depth=1,
        )
    }
    if actual_names != set(expected):
        raise IncompleteReconciliationPublicationError(
            "reconciliation output is incomplete or unexpected"
        )
    max_package_file_bytes = _required_limit(
        RECONCILIATION_PACKAGE_IO_LIMITS.max_file_bytes, "max_file_bytes"
    )
    for name, content in expected.items():
        observation = directory.observe_file(
            name, max_bytes=max_package_file_bytes
        )
        if (
            observation.byte_size != len(content)
            or observation.sha256 != hashlib.sha256(content).hexdigest()
        ):
            raise CollectionReconciliationError(
                "existing reconciliation output differs"
            )


def _bind_reconciliation_publication(
    parent: AuthorizedRoot,
    output_name: PurePosixPath,
    expected: dict[str, bytes],
) -> AuthorizedRoot:
    existing = AuthorizedRoot.existing(
        parent.child_path(output_name),
        label="reconciliation output directory",
        root_alias="reconciliation-output",
        storage_class=RootStorageClass.LOCAL,
    )
    _verify_reconciliation_publication(existing, expected)
    return existing


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPublicationRequest(DataObjectActionRequest):
    outputs: ReconciliationOutputs
    output_directory: Path
    output_storage_class: RootStorageClass


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPublicationResult(DataObjectActionResult):
    request: ReconciliationPublicationRequest
    publication: PublicationResult


@final
class ReconciliationPublisher(
    DataObjectActionizer[
        ReconciliationPublicationRequest, ReconciliationPublicationResult
    ]
):
    def action(
        self, *, request: ReconciliationPublicationRequest
    ) -> ReconciliationPublicationResult:
        if type(request) is not ReconciliationPublicationRequest:
            raise TypeError(
                "request must be a ReconciliationPublicationRequest"
            )
        outputs = request.outputs
        if type(outputs) is not ReconciliationOutputs:
            raise TypeError("outputs must be exact ReconciliationOutputs")
        try:
            outputs.validate()
        except ValueError as error:
            raise CollectionReconciliationError(str(error)) from error
        output_directory = request.output_directory
        output_storage_class = request.output_storage_class
        expected = dict(outputs.files)
        try:
            parsed = parse_package_files(expected)
        except ReconciliationPackageError as error:
            raise CollectionReconciliationError(str(error)) from error
        if parsed.manifest != outputs.package_manifest:
            raise CollectionReconciliationError(
                "in-memory package manifest differs from rendered bytes"
            )
        try:
            parent = AuthorizedRoot.create(
                output_directory.parent,
                label="reconciliation output parent",
                root_alias="reconciliation-output-parent",
                storage_class=output_storage_class,
            )
            output_name = validate_relative_path(
                output_directory.name, field="output directory name"
            )
            output_state = parent.state(output_name)
        except CloudRootMutationError, PlaceholderPreflightError:
            raise
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        if output_state == "regular":
            raise CollectionReconciliationError(
                "reconciliation output path is not a directory"
            )
        if output_state == "directory":
            try:
                _bind_reconciliation_publication(parent, output_name, expected)
            except PathLimitError as error:
                raise _limit_error(
                    error, RECONCILIATION_PACKAGE_IO_LIMITS
                ) from error
            except PathSafetyError as error:
                raise CollectionReconciliationError(str(error)) from error
            return ReconciliationPublicationResult(
                request=request,
                publication=PublicationResult(
                    status="unchanged",
                    output_directory=parent.child_path(output_name),
                    package_id=outputs.package_manifest.package_id,
                ),
            )
        try:
            published = parent.create_directory(output_name)
        except FileExistsError:
            try:
                _bind_reconciliation_publication(parent, output_name, expected)
            except PathLimitError as error:
                raise _limit_error(
                    error, RECONCILIATION_PACKAGE_IO_LIMITS
                ) from error
            except PathSafetyError as error:
                raise CollectionReconciliationError(str(error)) from error
            return ReconciliationPublicationResult(
                request=request,
                publication=PublicationResult(
                    status="unchanged",
                    output_directory=parent.child_path(output_name),
                    package_id=outputs.package_manifest.package_id,
                ),
            )
        try:
            for name in sorted(set(expected) - {PACKAGE_MANIFEST_FILENAME}):
                published.write_bytes(name, expected[name], replace=False)
            published.write_bytes(
                PACKAGE_MANIFEST_FILENAME,
                expected[PACKAGE_MANIFEST_FILENAME],
                replace=False,
            )
            _verify_reconciliation_publication(published, expected)
        except Exception as error:
            if isinstance(error, IncompleteReconciliationPublicationError):
                raise
            raise IncompleteReconciliationPublicationError(
                "reconciliation publication was claimed but did not complete"
            ) from error
        return ReconciliationPublicationResult(
            request=request,
            publication=PublicationResult(
                status="created",
                output_directory=parent.child_path(output_name),
                package_id=outputs.package_manifest.package_id,
            ),
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPackageParseRequest(DataObjectActionRequest):
    text: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPackageParseResult(DataObjectActionResult):
    request: ReconciliationPackageParseRequest
    manifest: ReconciliationPackageManifest


@final
class ReconciliationPackageParser(
    DataObjectActionizer[
        ReconciliationPackageParseRequest, ReconciliationPackageParseResult
    ]
):
    def action(
        self, *, request: ReconciliationPackageParseRequest
    ) -> ReconciliationPackageParseResult:
        if type(request) is not ReconciliationPackageParseRequest:
            raise TypeError(
                "request must be a ReconciliationPackageParseRequest"
            )
        text = request.text
        try:
            return ReconciliationPackageParseResult(
                request=request,
                manifest=ReconciliationPackageManifest.from_json(text),
            )
        except ValueError as error:
            raise CollectionReconciliationError(str(error)) from error


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPackageVerificationRequest(DataObjectActionRequest):
    directory: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = None
    expected_package_id: str | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPackageVerificationResult(DataObjectActionResult):
    request: ReconciliationPackageVerificationRequest
    package: LoadedReconciliationPackage


@final
class ReconciliationPackageVerifier(
    DataObjectActionizer[
        ReconciliationPackageVerificationRequest,
        ReconciliationPackageVerificationResult,
    ]
):
    def action(
        self, *, request: ReconciliationPackageVerificationRequest
    ) -> ReconciliationPackageVerificationResult:
        if type(request) is not ReconciliationPackageVerificationRequest:
            raise TypeError(
                "request must be a ReconciliationPackageVerificationRequest"
            )
        directory = request.directory
        storage_class = request.storage_class
        placeholder_probe = request.placeholder_probe
        expected_package_id = request.expected_package_id
        try:
            loaded = load_reconciliation_package(
                directory,
                storage_class=storage_class,
                placeholder_probe=placeholder_probe,
            )
        except ReconciliationPackageError as error:
            raise CollectionReconciliationError(str(error)) from error
        if (
            expected_package_id is not None
            and loaded.manifest.package_id != expected_package_id
        ):
            raise CollectionReconciliationError(
                "reconciliation package identity differs from expected identity"
            )
        return ReconciliationPackageVerificationResult(
            request=request, package=loaded
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationReplayRequest(DataObjectActionRequest):
    outputs: ReconciliationOutputs
    output_directory: Path
    output_storage_class: RootStorageClass


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationReplayResult(DataObjectActionResult):
    request: ReconciliationReplayRequest
    publication: PublicationResult


@final
class ReconciliationReplayer(
    DataObjectActionizer[
        ReconciliationReplayRequest, ReconciliationReplayResult
    ]
):
    def action(
        self, *, request: ReconciliationReplayRequest
    ) -> ReconciliationReplayResult:
        if type(request) is not ReconciliationReplayRequest:
            raise TypeError("request must be a ReconciliationReplayRequest")
        if type(request.outputs) is not ReconciliationOutputs:
            raise TypeError("outputs must be exact ReconciliationOutputs")
        publication = (
            ReconciliationPublisher()
            .action(
                request=ReconciliationPublicationRequest(
                    outputs=request.outputs,
                    output_directory=request.output_directory,
                    output_storage_class=request.output_storage_class,
                )
            )
            .publication
        )
        return ReconciliationReplayResult(
            request=request, publication=publication
        )
