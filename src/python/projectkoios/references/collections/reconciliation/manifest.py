from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.citation_closure import CitationClosure
from projectkoios.references.coverage import AmbiguityEvaluation, CoverageState
from projectkoios.references.reconciliation_package import (
    FrozenCounts,
    ReconciliationPackageManifest,
    pretty_json,
)
from projectkoios.references.state_projection import ReferenceStateProjection

from .classification import CollectionReference, ExtraPdf


@final
@dataclass(frozen=True)
class CollectionManifest(DataObjectModel):
    schema_version: int
    processor_version: str
    collection_id: str
    asserted_source_revision: str
    bibliography_sha256: str
    coverage_observation_id: str | None
    coverage_state: CoverageState | None
    ambiguity_evaluation: AmbiguityEvaluation
    coverage: tuple[str, ...]
    state_projections: tuple[ReferenceStateProjection, ...]
    references: tuple[CollectionReference, ...]
    extra_pdfs: tuple[ExtraPdf, ...]
    counts: FrozenCounts
    manifest_id: str

    def to_json(self) -> str:
        return pretty_json(self)


@final
@dataclass(frozen=True)
class ReconciliationOutputs(DataObjectModel):
    manifest: CollectionManifest
    citation_closure: CitationClosure | None
    package_manifest: ReconciliationPackageManifest
    files: tuple[tuple[str, bytes], ...]
