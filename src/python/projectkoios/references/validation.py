from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.io_limits import (
    VALIDATION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathLimitError,
    PlaceholderPreflightError,
    PlaceholderStatus,
    RootStorageClass,
    validate_citekey,
)

_CITEKEY_FIELD = re.compile(r'^citekey:\s*["\']?([^"\'\s]+)')


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def validate_reference_objects(
    records: tuple[ReferenceCandidate, ...],
    *,
    notes_directory: Path,
    notes_storage_class: RootStorageClass,
    pdf_directory: Path,
    pdf_storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = VALIDATION_IO_LIMITS,
) -> tuple[ValidationIssue, ...]:
    """Validate candidate-key basenames without granting acceptance."""
    max_candidates = _required_limit(limits.max_candidates, "max_candidates")
    if len(records) > max_candidates:
        raise ReferenceIOLimitError(
            resource="validation candidates",
            limit_name="max_candidates",
            limit=max_candidates,
            observed=len(records),
            limits=limits,
        )
    issues: list[ValidationIssue] = []
    keys = {validate_citekey(record.proposed_citekey) for record in records}
    notes = AuthorizedRoot.existing(
        notes_directory,
        label="notes root",
        root_alias="reference-notes",
        storage_class=notes_storage_class,
        placeholder_probe=(
            placeholder_probe
            if notes_storage_class is RootStorageClass.CLOUD_BACKED
            else None
        ),
    )
    pdfs = AuthorizedRoot.existing(
        pdf_directory,
        label="PDF root",
        root_alias="reference-pdfs",
        storage_class=pdf_storage_class,
        placeholder_probe=(
            placeholder_probe
            if pdf_storage_class is RootStorageClass.CLOUD_BACKED
            else None
        ),
    )
    try:
        max_entries_per_root = (
            _required_limit(limits.max_entries, "max_entries") // 2
        )
        note_files = notes.iter_files(
            suffix=".md",
            recursive=False,
            max_files=_required_limit(limits.max_files, "max_files"),
            max_entries=max_entries_per_root,
            max_depth=1,
        )
        pdf_files = pdfs.iter_files(
            suffix=".pdf",
            recursive=False,
            max_files=_required_limit(limits.max_files, "max_files"),
            max_entries=max_entries_per_root,
            max_depth=1,
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    total_files = len(note_files) + len(pdf_files)
    max_files = _required_limit(limits.max_files, "max_files")
    if total_files > max_files:
        raise ReferenceIOLimitError(
            resource="reference validation",
            limit_name="max_files",
            limit=max_files,
            observed=total_files,
            limits=limits,
        )
    total_bytes = 0
    for relative in note_files:
        preflight = notes.preflight_file(relative)
        if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
            raise PlaceholderPreflightError(preflight)
        stem = validate_citekey(Path(relative.name).stem)
        if stem not in keys:
            issues.append(
                ValidationIssue(
                    "orphan-note",
                    relative.name,
                    "note basename is not a bibliography key",
                )
            )
        declared, byte_size = _declared_citekey(
            notes,
            relative,
            limits=limits,
        )
        total_bytes += byte_size
        max_total_bytes = _required_limit(
            limits.max_text_total_bytes,
            "max_text_total_bytes",
        )
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="reference notes",
                limit_name="max_text_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=limits,
            )
        if declared is not None:
            validate_citekey(declared, field="declared citekey")
        if declared is not None and declared != stem:
            issues.append(
                ValidationIssue(
                    "note-citekey-mismatch",
                    relative.name,
                    f"frontmatter citekey is {declared!r}",
                )
            )
    for relative in pdf_files:
        preflight = pdfs.preflight_file(relative)
        if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
            raise PlaceholderPreflightError(preflight)
        stem = validate_citekey(Path(relative.name).stem)
        if stem not in keys:
            issues.append(
                ValidationIssue(
                    "orphan-pdf",
                    relative.name,
                    "PDF basename is not a bibliography key",
                )
            )
    return tuple(issues)


def _declared_citekey(
    root: AuthorizedRoot,
    relative: PurePosixPath,
    *,
    limits: ReferenceIOLimits,
) -> tuple[str | None, int]:
    max_file_bytes = _required_limit(
        limits.max_text_file_bytes,
        "max_text_file_bytes",
    )
    try:
        content = root.read_bytes(relative, max_bytes=max_file_bytes)
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    text = content.decode("utf-8")
    for number, line in enumerate(text.splitlines()):
        if number > 80 or (number > 0 and line.rstrip() == "---"):
            break
        match = _CITEKEY_FIELD.match(line.strip())
        if match:
            return match.group(1), len(content)
    return None, len(content)


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"validation I/O profile must define {name}")
    return value


def _limit_error(
    error: PathLimitError,
    limits: ReferenceIOLimits,
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource=error.resource,
        limit_name=error.limit_name,
        limit=error.limit,
        observed=error.observed,
        limits=limits,
    )
