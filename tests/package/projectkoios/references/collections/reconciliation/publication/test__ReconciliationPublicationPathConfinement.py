from __future__ import annotations

from pathlib import Path

import pytest
from projectkoios.references import (
    RootStorageClass,
)
from projectkoios.references.collections.reconciliation.errors import (
    CollectionReconciliationError,
)
from projectkoios.references.collections.reconciliation.loading import (
    CollectionRowEvidence,
)
from projectkoios.references.collections.reconciliation.publication import (
    ReconciliationPublicationRequest,
    ReconciliationPublisher,
)
from projectkoios.references.collections.reconciliation.reconciliation import (
    CollectionReconciler,
    CollectionReconciliationRequest,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
)


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


def test__publication__does_not_follow_output_directory_symlink(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "outputs"
    parent.mkdir()
    destination = parent / "fixture"
    destination.symlink_to(outside, target_is_directory=True)
    outputs = (
        CollectionReconciler()
        .action(
            request=CollectionReconciliationRequest(
                records=(_record(),),
                bibliography_bytes=b"fixture",
                collection_id="fixture",
                source_revision="asserted-revision",
                collection_rows={
                    "example2026": CollectionRowEvidence(
                        source_bibliographies=("references.bib",),
                        bibliographic_status="unverified",
                        reading_status="unread",
                    )
                },
                managed_pdfs=(),
                citation_closure=None,
            )
        )
        .outputs
    )

    with pytest.raises(CollectionReconciliationError, match="symlink"):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=destination,
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
    assert tuple(outside.iterdir()) == ()
