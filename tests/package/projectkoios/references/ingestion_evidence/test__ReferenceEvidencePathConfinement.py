from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from projectkoios.references import (
    PathSafetyError,
    RootStorageClass,
)
from projectkoios.references.collections.reconciliation.loading import (
    ManagedPdf,
)
from projectkoios.references.ingestion_evidence import (
    IngestionEvidenceVerificationError,
    load_ingestion_reference_evidence,
)
from projectkoios.references.ingestion_evidence import (
    ReferenceEvidenceInput as _ReferenceEvidenceInput,
)


def ReferenceEvidenceInput(citekey: str, path: Path) -> _ReferenceEvidenceInput:
    return _ReferenceEvidenceInput(citekey, path, RootStorageClass.LOCAL)


def test__reference_evidence_input__rejects_traversal_and_symlink_file(
    tmp_path: Path,
    ingestion_reference_evidence_fixture: Path,
) -> None:
    fixture_bytes = b"sanitized reference-evidence fixture source\n"
    fixture = ingestion_reference_evidence_fixture
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "evidence.json"
    external.write_bytes(fixture.read_bytes())

    with pytest.raises(PathSafetyError, match="citekey"):
        ReferenceEvidenceInput("../outside", external)

    link = tmp_path / "evidence.json"
    link.symlink_to(external)
    managed = ManagedPdf(
        filename="example2026.pdf",
        citekey="example2026",
        sha256=hashlib.sha256(fixture_bytes).hexdigest(),
        byte_size=len(fixture_bytes),
        historically_verified=False,
        discovery_evidence=(),
    )
    with pytest.raises(IngestionEvidenceVerificationError, match="symlink"):
        load_ingestion_reference_evidence(
            (ReferenceEvidenceInput("example2026", link),),
            managed_pdfs=(managed,),
        )
