from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references import (
    PathSafetyError,
    RootStorageClass,
)
from projectkoios.references.collections.reconciliation.errors import (
    CollectionReconciliationError,
)
from projectkoios.references.collections.reconciliation.loading import (
    ManagedPdfScanner,
    ManagedPdfScanRequest,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)
from projectkoios.references.validation import validate_reference_objects


def _record() -> ReferenceCandidate:
    return ReferenceCandidate.create(
        proposed_citekey="example2026",
        entry_type="article",
        title="Example",
        authors=("A. Author",),
        year="2026",
        source_observation_ids=("test-observation:sha256:" + "0" * 64,),
        generator=ProducerIdentity("test-fixture", "1"),
    )


def test__managed_pdf_and_object_validation__reject_symlinks(
    tmp_path: Path,
) -> None:
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-external")
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "example2026.pdf").symlink_to(outside_pdf)

    with pytest.raises(CollectionReconciliationError, match="symlink"):
        ManagedPdfScanner().action(
            request=ManagedPdfScanRequest(
                directory=pdfs, storage_class=RootStorageClass.LOCAL
            )
        )

    notes = tmp_path / "notes"
    notes.mkdir()
    outside_note = tmp_path / "outside.md"
    outside_note.write_text("citekey: example2026\n", encoding="utf-8")
    (notes / "example2026.md").symlink_to(outside_note)
    with pytest.raises(PathSafetyError, match="symlink"):
        validate_reference_objects(
            (_record(),),
            notes_directory=notes,
            notes_storage_class=RootStorageClass.LOCAL,
            pdf_directory=pdfs,
            pdf_storage_class=RootStorageClass.LOCAL,
        )
