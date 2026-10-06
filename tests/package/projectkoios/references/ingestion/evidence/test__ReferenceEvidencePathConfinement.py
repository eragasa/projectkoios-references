from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path

import pytest
from projectkoios.references.adapters.filesystem.macos.file.provider.placeholder.probe import (  # noqa: E501
    MacOSFileProviderPlaceholderProbe,
)
from projectkoios.references.citation.key.error import CitationKeyError
from projectkoios.references.collections.reconciliation.loading import (
    ManagedPdf,
)
from projectkoios.references.filesystem.path.read import read_path_bytes
from projectkoios.references.filesystem.root.preflight.error import (
    PlaceholderPreflightError,
)
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)
from projectkoios.references.ingestion.evidence.error import (
    IngestionEvidenceVerificationError,
)
from projectkoios.references.ingestion.evidence.input import (
    ReferenceEvidenceInput as _ReferenceEvidenceInput,
)
from projectkoios.references.ingestion.evidence.loading.action import (
    load_ingestion_reference_evidence,
)


def ReferenceEvidenceInput(citekey: str, path: Path) -> _ReferenceEvidenceInput:
    return _ReferenceEvidenceInput(citekey, path, RootStorageClass.LOCAL)


@pytest.mark.skipif(
    sys.platform != "darwin" or not hasattr(stat, "SF_DATALESS"),
    reason="requires macOS File Provider metadata support",
)
def test__reference_evidence_input__accepts_root_bound_probe_factory(
    tmp_path: Path,
) -> None:
    content = b"factory-bound evidence"
    path = tmp_path / "evidence.json"
    path.write_bytes(content)
    factory = MacOSFileProviderPlaceholderProbe(tmp_path)
    binding = _ReferenceEvidenceInput(
        "example2026",
        path,
        RootStorageClass.CLOUD_BACKED,
        factory,
    )

    assert binding.placeholder_probe is factory
    with pytest.raises(PlaceholderPreflightError, match="access-controlled"):
        read_path_bytes(
            binding.path,
            label="reference evidence",
            root_alias="reference-evidence-example2026",
            storage_class=binding.storage_class,
            placeholder_probe=binding.placeholder_probe,
        )


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

    with pytest.raises(CitationKeyError, match="citekey"):
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
