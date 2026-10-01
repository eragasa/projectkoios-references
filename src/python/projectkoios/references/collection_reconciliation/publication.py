from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from projectkoios.references.io_limits import (
    RECONCILIATION_PACKAGE_IO_LIMITS,
)
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

from ._contract import (
    _limit_error,
    _required_limit,
)
from .models import (
    CollectionReconciliationError,
    IncompleteReconciliationPublicationError,
    PublicationResult,
    ReconciliationOutputs,
)


def _verify_reconciliation_publication(
    directory: AuthorizedRoot,
    expected: dict[str, bytes],
) -> None:
    if directory.state(PACKAGE_MANIFEST_FILENAME) != "regular":
        raise IncompleteReconciliationPublicationError(
            "reconciliation output has no completion manifest"
        )
    directory_limit = min(
        _required_limit(
            RECONCILIATION_PACKAGE_IO_LIMITS.max_entries,
            "max_entries",
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
        RECONCILIATION_PACKAGE_IO_LIMITS.max_file_bytes,
        "max_file_bytes",
    )
    for name, content in expected.items():
        observation = directory.observe_file(
            name,
            max_bytes=max_package_file_bytes,
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


def publish_reconciliation(
    outputs: ReconciliationOutputs,
    *,
    output_directory: Path,
    output_storage_class: RootStorageClass,
) -> PublicationResult:
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
            output_directory.name,
            field="output directory name",
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
                error,
                RECONCILIATION_PACKAGE_IO_LIMITS,
            ) from error
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        return PublicationResult(
            status="unchanged",
            output_directory=parent.child_path(output_name),
            package_id=outputs.package_manifest.package_id,
        )

    try:
        published = parent.create_directory(output_name)
    except FileExistsError:
        try:
            _bind_reconciliation_publication(parent, output_name, expected)
        except PathLimitError as error:
            raise _limit_error(
                error,
                RECONCILIATION_PACKAGE_IO_LIMITS,
            ) from error
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        return PublicationResult(
            status="unchanged",
            output_directory=parent.child_path(output_name),
            package_id=outputs.package_manifest.package_id,
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
    return PublicationResult(
        status="created",
        output_directory=parent.child_path(output_name),
        package_id=outputs.package_manifest.package_id,
    )


def parse_reconciliation_package(
    text: str,
) -> ReconciliationPackageManifest:
    try:
        return ReconciliationPackageManifest.from_json(text)
    except ValueError as error:
        raise CollectionReconciliationError(str(error)) from error


def verify_reconciliation_package(
    directory: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    expected_package_id: str | None = None,
) -> LoadedReconciliationPackage:
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
    return loaded


def replay_reconciliation(
    outputs: ReconciliationOutputs,
    *,
    output_directory: Path,
    output_storage_class: RootStorageClass,
) -> PublicationResult:
    """Replay deterministic bytes through immutable publication semantics."""
    return publish_reconciliation(
        outputs,
        output_directory=output_directory,
        output_storage_class=output_storage_class,
    )
