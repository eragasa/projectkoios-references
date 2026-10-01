from __future__ import annotations

from dataclasses import dataclass
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.citation_closure import CitationClosure
from projectkoios.references.coverage import AmbiguityEvaluation, CoverageState
from projectkoios.references.reconciliation_package import (
    PACKAGE_MANIFEST_FILENAME,
    FrozenCounts,
    ReconciliationPackageError,
    ReconciliationPackageManifest,
    parse_package_files,
    pretty_json,
)
from projectkoios.references.state_projection import ReferenceStateProjection

from ._contract import _SCHEMA_VERSION
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

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self.manifest) is not CollectionManifest:
            raise ValueError("manifest must be an exact CollectionManifest")
        if self.citation_closure is not None and (
            type(self.citation_closure) is not CitationClosure
        ):
            raise ValueError("citation closure must have its exact type")
        if type(self.package_manifest) is not ReconciliationPackageManifest:
            raise ValueError(
                "package manifest must have its exact canonical type"
            )
        if type(self.files) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not bytes
            for item in self.files
        ):
            raise ValueError("output files must be exact filename/byte tuples")
        names = tuple(name for name, _ in self.files)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError(
                "output filenames must be canonical, sorted, and unique"
            )
        files = dict(self.files)
        if files.get(
            "collection-manifest.json"
        ) != self.manifest.to_json().encode("utf-8"):
            raise ValueError(
                "rendered collection manifest differs from its data object"
            )
        expected_closure = (
            self.citation_closure.to_json().encode("utf-8")
            if self.citation_closure is not None
            else pretty_json(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "status": "not-supplied",
                    "asserted_source_revision": (
                        self.manifest.asserted_source_revision
                    ),
                }
            ).encode("utf-8")
        )
        if files.get("citation-closure.json") != expected_closure:
            raise ValueError(
                "rendered citation closure differs from its data object"
            )
        if files.get(PACKAGE_MANIFEST_FILENAME) != (
            self.package_manifest.to_json().encode("utf-8")
        ):
            raise ValueError(
                "rendered package manifest differs from its data object"
            )
        try:
            parsed = parse_package_files(files)
        except ReconciliationPackageError as error:
            raise ValueError(str(error)) from error
        if parsed.manifest != self.package_manifest:
            raise ValueError(
                "parsed package manifest differs from its data object"
            )
