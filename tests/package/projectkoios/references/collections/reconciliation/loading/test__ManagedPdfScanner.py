from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references.collections.reconciliation.errors import (
    CollectionReconciliationError,
)
from projectkoios.references.collections.reconciliation.loading import (
    ManagedPdfScanner,
    ManagedPdfScanRequest,
)
from projectkoios.references.path_safety import RootStorageClass


def test__ManagedPdfScanner__rejects_non_pdf_bytes(tmp_path: Path) -> None:
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "notPdf.pdf").write_text("not a PDF", encoding="utf-8")
    with pytest.raises(CollectionReconciliationError, match="lacks PDF header"):
        ManagedPdfScanner().action(
            request=ManagedPdfScanRequest(
                directory=pdfs, storage_class=RootStorageClass.LOCAL
            )
        )
