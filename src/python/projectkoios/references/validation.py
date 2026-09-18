from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from projectkoios.references.models import ReferenceRecord

_CITEKEY_FIELD = re.compile(r'^citekey:\s*["\']?([^"\'\s]+)')


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    message: str


def validate_reference_objects(
    records: tuple[ReferenceRecord, ...],
    *,
    notes_directory: Path,
    pdf_directory: Path,
) -> tuple[ValidationIssue, ...]:
    """Validate canonical basenames without requiring every optional PDF."""
    issues: list[ValidationIssue] = []
    keys = {record.citekey for record in records}
    for note in sorted(notes_directory.glob("*.md")):
        if note.stem not in keys:
            issues.append(
                ValidationIssue(
                    "orphan-note",
                    note.name,
                    "note basename is not a bibliography key",
                )
            )
        declared = _declared_citekey(note)
        if declared is not None and declared != note.stem:
            issues.append(
                ValidationIssue(
                    "note-citekey-mismatch",
                    note.name,
                    f"frontmatter citekey is {declared!r}",
                )
            )
    for pdf in sorted(pdf_directory.glob("*.pdf")):
        if pdf.stem not in keys:
            issues.append(
                ValidationIssue(
                    "orphan-pdf",
                    pdf.name,
                    "PDF basename is not a bibliography key",
                )
            )
    return tuple(issues)


def _declared_citekey(path: Path) -> str | None:
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream):
            if number > 80 or (number > 0 and line.rstrip() == "---"):
                break
            match = _CITEKEY_FIELD.match(line.strip())
            if match:
                return match.group(1)
    return None
