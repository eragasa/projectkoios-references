from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.path_safety import (
    AuthorizedRoot,
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
    pdf_directory: Path,
) -> tuple[ValidationIssue, ...]:
    """Validate candidate-key basenames without granting acceptance."""
    issues: list[ValidationIssue] = []
    keys = {validate_citekey(record.proposed_citekey) for record in records}
    notes = AuthorizedRoot.existing(notes_directory, label="notes root")
    pdfs = AuthorizedRoot.existing(pdf_directory, label="PDF root")
    for relative in notes.iter_files(suffix=".md", recursive=False):
        stem = validate_citekey(Path(relative.name).stem)
        if stem not in keys:
            issues.append(
                ValidationIssue(
                    "orphan-note",
                    relative.name,
                    "note basename is not a bibliography key",
                )
            )
        declared = _declared_citekey(notes, relative)
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
    for relative in pdfs.iter_files(suffix=".pdf", recursive=False):
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
) -> str | None:
    text = root.read_text(relative)
    for number, line in enumerate(text.splitlines()):
        if number > 80 or (number > 0 and line.rstrip() == "---"):
            break
        match = _CITEKEY_FIELD.match(line.strip())
        if match:
            return match.group(1)
    return None
