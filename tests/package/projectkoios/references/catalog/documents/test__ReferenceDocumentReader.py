from __future__ import annotations

import json
from pathlib import Path

import projectkoios.base as base
import projectkoios.references.catalog as catalog
import projectkoios.references.identity as identity
import projectkoios.references.models as models
import projectkoios.references.review as review
import pytest
from projectkoios.references.filesystem.root.preflight.storage import (
    RootStorageClass,
)


class _CatalogAccessTrap:
    """Fail if a PUBLIC read attempts private catalog access."""

    def read_candidates(self) -> tuple[identity.ReferenceCandidate, ...]:
        raise AssertionError("PUBLIC read accessed candidates")

    def read_observations(
        self,
    ) -> tuple[identity.SourceBibliographyObservation, ...]:
        raise AssertionError("PUBLIC read accessed observations")

    def read_source_assets(
        self,
        *,
        max_records: int | None = None,
    ) -> tuple[models.SourceAssetRecord, ...]:
        raise AssertionError(
            f"PUBLIC read accessed assets with limit {max_records!r}"
        )

    def read_review_projection(self) -> review.ReviewProjection:
        raise AssertionError("PUBLIC read accessed review state")


def _registry() -> catalog.ReferenceDocumentRegistry:
    return catalog.ReferenceDocumentRegistry(
        bindings=(
            catalog.ReferenceDocumentBinding(
                document_id="doc-01",
                proposed_citekey="kittel2005",
                collection_id="solidstate",
                collection_label="Solid State Physics",
                filename="Kittel8ed.pdf",
            ),
        )
    )


def _catalog(path: Path) -> catalog.ReferenceCatalog:
    value = catalog.ReferenceCatalog(
        path,
        storage_class=RootStorageClass.LOCAL,
    )
    value.initialize()
    bibliography = b"@book{kittel2005, title={Introduction}}\n"
    observation = identity.SourceBibliographyObservation.create(
        source_id="catalog-collection:solidstate",
        asserted_source_revision=None,
        source_path="solidstate.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey="kittel2005",
        verbatim_entry=bibliography.decode().strip(),
        parser=identity.ProducerIdentity("test-parser", "1"),
    )
    candidate = identity.ReferenceCandidate.create(
        proposed_citekey="kittel2005",
        entry_type="book",
        title="Introduction to Solid State Physics",
        authors=("Kittel, Charles",),
        year="2005",
        source_observation_ids=(observation.observation_id,),
        generator=identity.ProducerIdentity("test-normalizer", "1"),
    )
    value.import_candidates((candidate,), (observation,))
    value.record_source_asset(
        models.SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.lifecycle_status,
            citekey_status=candidate.citekey_status,
            sha256="a" * 64,
            byte_size=100,
            root_alias="private-references",
            relative_path="textbooks/Kittel8ed.pdf",
            rights_status="not-assessed",
            asset_status="observed-source-copy",
        )
    )
    return value


def test__ReferenceDocumentReader__uses_explicit_reference_identity(
    tmp_path: Path,
) -> None:
    registry = _registry()
    reader = catalog.ReferenceDocumentReader(
        catalog=_catalog(tmp_path / "references.sqlite3"),
        registry=registry,
    )
    request = catalog.ReferenceDocumentReadRequest(
        registry_id=registry.registry_id,
        audience=catalog.ReferenceDocumentAudience.CONTROL,
    )

    result = reader.action(request=request)

    assert issubclass(catalog.ReferenceDocumentBinding, base.DataObjectModel)
    assert issubclass(
        catalog.ReferenceDocumentReadRequest,
        base.DataObjectActionRequest,
    )
    assert issubclass(
        catalog.ReferenceDocumentReadResult,
        base.DataObjectActionResult,
    )
    assert issubclass(
        catalog.ReferenceDocumentReader,
        base.DataObjectActionizer,
    )
    assert result.request is request
    assert len(result.documents) == 1
    document = result.documents[0]
    assert document.document_id == "doc-01"
    assert document.proposed_citekey == "kittel2005"
    assert document.filename == "Kittel8ed.pdf"
    assert document.collection_id == "solidstate"
    assert document.source_asset_count == 1
    assert document.publication_eligibility == "not-established"


def test__public_documents__are_empty_without_catalog_access() -> None:
    registry = _registry()
    reader = catalog.ReferenceDocumentReader(
        catalog=_CatalogAccessTrap(),
        registry=registry,
    )

    result = reader.action(
        request=catalog.ReferenceDocumentReadRequest(
            registry_id=registry.registry_id,
            audience=catalog.ReferenceDocumentAudience.PUBLIC,
        )
    )

    assert result.documents == ()


def test__public_lookup__fails_without_catalog_access() -> None:
    registry = _registry()
    reader = catalog.ReferenceDocumentReader(
        catalog=_CatalogAccessTrap(),
        registry=registry,
    )

    with pytest.raises(
        catalog.ReferenceDocumentNotFound,
        match="doc-01.*was not found",
    ):
        reader.action(
            request=catalog.ReferenceDocumentReadRequest(
                registry_id=registry.registry_id,
                audience=catalog.ReferenceDocumentAudience.PUBLIC,
                document_id="doc-01",
            )
        )


def test__ReferenceDocumentReader__reads_one_document_without_search(
    tmp_path: Path,
) -> None:
    registry = _registry()
    reader = catalog.ReferenceDocumentReader(
        catalog=_catalog(tmp_path / "references.sqlite3"),
        registry=registry,
    )

    result = reader.action(
        request=catalog.ReferenceDocumentReadRequest(
            registry_id=registry.registry_id,
            audience=catalog.ReferenceDocumentAudience.CONTROL,
            document_id="doc-01",
        )
    )

    assert tuple(item.document_id for item in result.documents) == ("doc-01",)


def test__ReferenceDocumentReader__allows_a_bounded_catalog_slice(
    tmp_path: Path,
) -> None:
    catalog_value = _catalog(tmp_path / "references.sqlite3")
    bibliography = b"@book{other2006, title={Another Reference}}\n"
    observation = identity.SourceBibliographyObservation.create(
        source_id="catalog-collection:other",
        asserted_source_revision=None,
        source_path="other.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey="other2006",
        verbatim_entry=bibliography.decode().strip(),
        parser=identity.ProducerIdentity("test-parser", "1"),
    )
    candidate = identity.ReferenceCandidate.create(
        proposed_citekey="other2006",
        entry_type="book",
        title="Another Reference",
        authors=("Other, Author",),
        year="2006",
        source_observation_ids=(observation.observation_id,),
        generator=identity.ProducerIdentity("test-normalizer", "1"),
    )
    catalog_value.import_candidates((candidate,), (observation,))
    catalog_value.record_source_asset(
        models.SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.lifecycle_status,
            citekey_status=candidate.citekey_status,
            sha256="b" * 64,
            byte_size=200,
            root_alias="private-references",
            relative_path="other/Another.pdf",
            rights_status="not-assessed",
            asset_status="observed-source-copy",
        )
    )
    registry = _registry()
    reader = catalog.ReferenceDocumentReader(
        catalog=catalog_value,
        registry=registry,
    )

    result = reader.action(
        request=catalog.ReferenceDocumentReadRequest(
            registry_id=registry.registry_id,
            audience=catalog.ReferenceDocumentAudience.CONTROL,
        )
    )

    assert tuple(item.document_id for item in result.documents) == ("doc-01",)


def test__ReferenceDocumentReader__rejects_unbound_asset_candidate(
    tmp_path: Path,
) -> None:
    registry = catalog.ReferenceDocumentRegistry(
        bindings=(
            catalog.ReferenceDocumentBinding(
                document_id="doc-99",
                proposed_citekey="other2005",
                collection_id="solidstate",
                collection_label="Solid State Physics",
                filename="Other.pdf",
            ),
        )
    )
    reader = catalog.ReferenceDocumentReader(
        catalog=_catalog(tmp_path / "references.sqlite3"),
        registry=registry,
    )

    with pytest.raises(
        catalog.ReferenceDocumentReadError,
        match="registry differs",
    ):
        reader.action(
            request=catalog.ReferenceDocumentReadRequest(
                registry_id=registry.registry_id,
                audience=catalog.ReferenceDocumentAudience.CONTROL,
            )
        )


def test__ReferenceDocumentRegistry__round_trips_canonical_json() -> None:
    registry = _registry()

    mapping = registry.to_dict()
    encoded = registry.to_json()
    loaded_mapping = json.loads(encoded)
    loaded = catalog.ReferenceDocumentRegistry.from_json(encoded)

    assert loaded_mapping == mapping
    assert catalog.ReferenceDocumentRegistry.from_dict(mapping) == registry
    assert loaded == registry
    assert loaded.registry_id == registry.registry_id
    assert loaded.bindings[0].to_dict() == mapping["documents"][0]
    assert (
        catalog.ReferenceDocumentBinding.from_dict(loaded.bindings[0].to_dict())
        == loaded.bindings[0]
    )


def test__ReferenceDocumentRegistry__rejects_duplicate_filenames() -> None:
    binding = catalog.ReferenceDocumentBinding(
        document_id="doc-01",
        proposed_citekey="first2005",
        collection_id="solidstate",
        collection_label="Solid State Physics",
        filename="Shared.pdf",
    )
    duplicate = catalog.ReferenceDocumentBinding(
        document_id="doc-02",
        proposed_citekey="second2005",
        collection_id="solidstate",
        collection_label="Solid State Physics",
        filename="Shared.pdf",
    )

    with pytest.raises(
        catalog.ReferenceDocumentReadError,
        match="duplicate filenames",
    ):
        catalog.ReferenceDocumentRegistry(bindings=(binding, duplicate))
