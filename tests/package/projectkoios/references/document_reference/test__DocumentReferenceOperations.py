from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from projectkoios.references.adapters.bibliography import (
    pybtex_metadata_reader,
)
from projectkoios.references.adapters.filesystem import (
    sha256_pdf_object_store,
)
from projectkoios.references.adapters.sql.sqlite import (
    document_reference_store,
)
from projectkoios.references.document_reference.bibliography.metadata.errors import (  # noqa: E501
    BibliographyMetadataError,
)
from projectkoios.references.document_reference.bibliography.record import (
    ReferenceRecord,
)
from projectkoios.references.document_reference.bindings.basis import (
    ReferenceDocumentLinkageBasis,
)
from projectkoios.references.document_reference.bindings.disposition import (
    BindingDisposition,
)
from projectkoios.references.document_reference.bindings.errors import (
    ReferenceDocumentBindingConflict,
)
from projectkoios.references.document_reference.bindings.explicit.action import (  # noqa: E501
    BindPdfToReference,
)
from projectkoios.references.document_reference.bindings.explicit.request import (  # noqa: E501
    BindPdfToReferenceRequest,
)
from projectkoios.references.document_reference.bindings.verified_local.action import (  # noqa: E501
    BindVerifiedLocalEvidence,
)
from projectkoios.references.document_reference.bindings.verified_local.request import (  # noqa: E501
    BindVerifiedLocalEvidenceRequest,
)
from projectkoios.references.document_reference.collections.collection import (
    ReferenceCollection,
)
from projectkoios.references.document_reference.collections.membership import (
    ReferenceCollectionMembership,
)
from projectkoios.references.document_reference.collections.missing.action import (  # noqa: E501
    ListMissingPdfReferences,
)
from projectkoios.references.document_reference.collections.missing.request import (  # noqa: E501
    ListMissingPdfReferencesRequest,
)
from projectkoios.references.document_reference.collections.pdf_requirement import (  # noqa: E501
    PdfRequirement,
)
from projectkoios.references.document_reference.documents.errors import (
    DocumentContentConflict,
)
from projectkoios.references.document_reference.documents.receipt.action import (  # noqa: E501
    ReceivePdf,
)
from projectkoios.references.document_reference.documents.receipt.disposition import (  # noqa: E501
    PdfReceiptDisposition,
)
from projectkoios.references.document_reference.documents.receipt.errors import (  # noqa: E501
    InvalidPdfUpload,
    PdfUploadTooLarge,
)
from projectkoios.references.document_reference.documents.receipt.request import (  # noqa: E501
    ReceivePdfRequest,
)
from projectkoios.references.document_reference.intake.action import (
    ProvideReferencePdf,
)
from projectkoios.references.document_reference.intake.request import (
    ProvideReferencePdfRequest,
)
from projectkoios.references.document_reference.intake.status import (
    ReferencePdfProvisionStatus,
)
from projectkoios.references.path_safety.preflight import RootStorageClass
from projectkoios.references.path_safety.root import AuthorizedRoot

PybtexBibliographyMetadataReader = (
    pybtex_metadata_reader.PybtexBibliographyMetadataReader
)
Sha256PdfObjectStore = sha256_pdf_object_store.Sha256PdfObjectStore
SqliteDocumentReferenceStore = (
    document_reference_store.SqliteDocumentReferenceStore
)

_PDF_ONE = b"%PDF-1.7\nsanitized fixture one\n%%EOF\n"
_PDF_TWO = b"%PDF-1.7\nsanitized fixture two\n%%EOF\n"


@dataclass(frozen=True, slots=True)
class _Harness:
    store: SqliteDocumentReferenceStore
    receive: ReceivePdf
    list_missing: ListMissingPdfReferences
    bind: BindPdfToReference
    bind_verified: BindVerifiedLocalEvidence
    provide: ProvideReferencePdf
    object_path: Path


def _root(path: Path, *, alias: str) -> AuthorizedRoot:
    return AuthorizedRoot.create(
        path,
        label=alias,
        root_alias=alias,
        storage_class=RootStorageClass.LOCAL,
    )


def _harness(tmp_path: Path, *, max_pdf_bytes: int = 128) -> _Harness:
    database_root = _root(tmp_path / "database", alias="test-database")
    object_path = tmp_path / "objects"
    object_root = _root(object_path, alias="test-pdf-objects")
    store = SqliteDocumentReferenceStore(
        database_root=database_root,
        database_name="document-reference.sqlite3",
        metadata_reader=PybtexBibliographyMetadataReader(),
    )
    store.initialize()
    objects = Sha256PdfObjectStore(
        root=object_root,
        max_pdf_bytes=max_pdf_bytes,
    )
    receive = ReceivePdf(objects=objects, repository=store)
    bind = BindPdfToReference(repository=store)
    return _Harness(
        store=store,
        receive=receive,
        list_missing=ListMissingPdfReferences(repository=store),
        bind=bind,
        bind_verified=BindVerifiedLocalEvidence(repository=store),
        provide=ProvideReferencePdf(receive=receive, bind=bind),
        object_path=object_path,
    )


def _seed(harness: _Harness) -> None:
    entries = {
        "requiredOne": (
            "@article{requiredOne, title={Sanitized title}, "
            "author={Example, Alice and Example, Bob}, year={2025}}"
        ),
        "requiredTwo": "@misc{requiredTwo, note={Metadata not established}}",
        "webOnly": "@online{webOnly, title={Sanitized website}}",
    }
    for citekey, bibtex_entry in entries.items():
        harness.store.record_reference(
            reference=ReferenceRecord(
                citekey=citekey,
                bibtex_entry=bibtex_entry,
            )
        )
    harness.store.record_collection(
        collection=ReferenceCollection(
            collection_id="ksdft2effmass",
            source_id="sanitized-monograph",
            source_revision="revision-1",
        )
    )
    for citekey, requirement in (
        ("requiredOne", PdfRequirement.REQUIRED),
        ("requiredTwo", PdfRequirement.REQUIRED),
        ("webOnly", PdfRequirement.NOT_APPLICABLE),
    ):
        harness.store.record_membership(
            membership=ReferenceCollectionMembership(
                collection_id="ksdft2effmass",
                citekey=citekey,
                pdf_requirement=requirement,
            )
        )


def _receive(
    harness: _Harness,
    content: bytes,
    *,
    source_link: str | None = "https://example.test/sanitized.pdf",
):
    return harness.receive.receive(
        request=ReceivePdfRequest(
            source_link=source_link,
            declared_byte_size=len(content),
        ),
        stream=io.BytesIO(content),
    )


def test__document_reference_operations__derive_missing_then_bind_idempotently(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed(harness)

    before = harness.list_missing.action(
        request=ListMissingPdfReferencesRequest(collection_id="ksdft2effmass")
    )

    assert before.source_id == "sanitized-monograph"
    assert before.source_revision == "revision-1"
    assert before.required_count == 2
    assert before.bound_count == 0
    assert before.not_applicable_count == 1
    assert tuple(row.citekey for row in before.missing) == (
        "requiredOne",
        "requiredTwo",
    )
    assert before.missing[0].entry_type == "article"
    assert before.missing[0].title == "Sanitized title"
    assert before.missing[0].authors == (
        "Example, Alice",
        "Example, Bob",
    )
    assert before.missing[0].year == "2025"
    assert before.missing[1].entry_type == "misc"
    assert before.missing[1].title is None
    assert before.missing[1].authors == ()
    assert before.missing[1].year is None
    assert all(not hasattr(row, "bibtex_entry") for row in before.missing)
    assert all(not hasattr(row, "source_link") for row in before.missing)

    receipt = _receive(harness, _PDF_ONE)
    request = BindPdfToReferenceRequest(
        collection_id="ksdft2effmass",
        citekey="requiredOne",
        document_sha256=receipt.sha256,
    )
    created = harness.bind.action(request=request)
    repeated = harness.bind.action(request=request)
    after = harness.list_missing.action(
        request=ListMissingPdfReferencesRequest(collection_id="ksdft2effmass")
    )

    assert receipt.disposition is PdfReceiptDisposition.RECEIVED
    assert created.disposition is BindingDisposition.BOUND
    assert repeated.disposition is BindingDisposition.ALREADY_BOUND
    assert after.bound_count == 1
    assert tuple(row.citekey for row in after.missing) == ("requiredTwo",)


def test__document_reference_operations__reject_invalid_display_metadata(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    with pytest.raises(BibliographyMetadataError):
        harness.store.record_reference(
            reference=ReferenceRecord(
                citekey="oversizedTitle",
                bibtex_entry=(
                    "@article{oversizedTitle, title={" + "x" * 2_001 + "}}"
                ),
            )
        )

    harness.store.record_reference(
        reference=ReferenceRecord(
            citekey="storedEntry",
            bibtex_entry="@article{storedEntry, title={Valid}}",
        )
    )
    harness.store.record_collection(
        collection=ReferenceCollection(
            collection_id="collection",
            source_id="sanitized-source",
            source_revision="revision-1",
        )
    )
    harness.store.record_membership(
        membership=ReferenceCollectionMembership(
            collection_id="collection",
            citekey="storedEntry",
            pdf_requirement=PdfRequirement.REQUIRED,
        )
    )
    connection = sqlite3.connect(harness.store.database_path)
    try:
        connection.execute(
            "UPDATE reference_records SET bibtex_entry = ? WHERE citekey = ?",
            ("not BibTeX", "storedEntry"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(BibliographyMetadataError):
        harness.list_missing.action(
            request=ListMissingPdfReferencesRequest(collection_id="collection")
        )


def test__document_reference_operations__deduplicate_and_retain_sources(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    first = _receive(
        harness,
        _PDF_ONE,
        source_link="https://example.test/source-one.pdf",
    )
    repeated = _receive(
        harness,
        _PDF_ONE,
        source_link="https://example.test/source-one.pdf",
    )
    second_source = _receive(
        harness,
        _PDF_ONE,
        source_link="https://example.test/source-two.pdf",
    )

    assert first.sha256 == repeated.sha256 == second_source.sha256
    assert first.disposition is PdfReceiptDisposition.RECEIVED
    assert repeated.disposition is PdfReceiptDisposition.ALREADY_PRESENT
    assert (
        second_source.disposition
        is PdfReceiptDisposition.SOURCE_OBSERVATION_ADDED
    )
    assert [item.name for item in harness.object_path.iterdir()] == [
        f"{first.sha256}.pdf"
    ]
    connection = sqlite3.connect(harness.store.database_path)
    try:
        assert connection.execute(
            "SELECT source_link FROM document_receipts ORDER BY source_link"
        ).fetchall() == [
            ("https://example.test/source-one.pdf",),
            ("https://example.test/source-two.pdf",),
        ]
    finally:
        connection.close()


def test__document_reference_operations__reject_corrupt_deduplication(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    first = _receive(
        harness,
        _PDF_ONE,
        source_link="https://example.test/source-one.pdf",
    )
    object_path = harness.object_path / f"{first.sha256}.pdf"
    object_path.write_bytes(b"%PDF-corrupt")

    with pytest.raises(DocumentContentConflict):
        _receive(
            harness,
            _PDF_ONE,
            source_link="https://example.test/source-two.pdf",
        )

    connection = sqlite3.connect(harness.store.database_path)
    try:
        assert connection.execute(
            "SELECT source_link FROM document_receipts"
        ).fetchall() == [("https://example.test/source-one.pdf",)]
    finally:
        connection.close()


def test__document_reference_operations__binding_conflicts_are_atomic(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed(harness)
    first = _receive(harness, _PDF_ONE)
    second = _receive(
        harness,
        _PDF_TWO,
        source_link="https://example.test/second.pdf",
    )
    harness.bind.action(
        request=BindPdfToReferenceRequest(
            collection_id="ksdft2effmass",
            citekey="requiredOne",
            document_sha256=first.sha256,
        )
    )

    with pytest.raises(ReferenceDocumentBindingConflict):
        harness.bind.action(
            request=BindPdfToReferenceRequest(
                collection_id="ksdft2effmass",
                citekey="requiredOne",
                document_sha256=second.sha256,
            )
        )
    with pytest.raises(ReferenceDocumentBindingConflict):
        harness.bind.action(
            request=BindPdfToReferenceRequest(
                collection_id="ksdft2effmass",
                citekey="requiredTwo",
                document_sha256=first.sha256,
            )
        )
    with pytest.raises(
        ReferenceDocumentBindingConflict, match="does not require"
    ):
        harness.bind.action(
            request=BindPdfToReferenceRequest(
                collection_id="ksdft2effmass",
                citekey="webOnly",
                document_sha256=second.sha256,
            )
        )

    connection = sqlite3.connect(harness.store.database_path)
    try:
        assert connection.execute(
            "SELECT citekey, document_sha256 FROM reference_document_bindings"
        ).fetchall() == [("requiredOne", first.sha256)]
    finally:
        connection.close()


def test__document_reference_operations__preserve_binding_provenance_and_replay(
    tmp_path: Path,
) -> None:
    explicit = _harness(tmp_path / "explicit")
    _seed(explicit)
    explicit_receipt = _receive(explicit, _PDF_ONE)
    explicit_result = explicit.bind.action(
        request=BindPdfToReferenceRequest(
            collection_id="ksdft2effmass",
            citekey="requiredOne",
            document_sha256=explicit_receipt.sha256,
        )
    )
    with pytest.raises(ReferenceDocumentBindingConflict):
        explicit.bind_verified.action(
            request=BindVerifiedLocalEvidenceRequest(
                collection_id="ksdft2effmass",
                citekey="requiredOne",
                document_sha256=explicit_receipt.sha256,
            )
        )

    imported = _harness(tmp_path / "imported")
    _seed(imported)
    imported_receipt = _receive(imported, _PDF_ONE)
    request = BindVerifiedLocalEvidenceRequest(
        collection_id="ksdft2effmass",
        citekey="requiredOne",
        document_sha256=imported_receipt.sha256,
    )
    imported_result = imported.bind_verified.action(request=request)
    imported_replay = imported.bind_verified.action(request=request)

    assert (
        explicit_result.binding.linkage_basis
        is ReferenceDocumentLinkageBasis.EXPLICIT_SELECTION
    )
    assert (
        imported_result.binding.linkage_basis
        is ReferenceDocumentLinkageBasis.VERIFIED_LOCAL_EVIDENCE_IMPORT
    )
    assert explicit_result.binding.binding_id == (
        "reference-document-binding:sha256:"
        "8a6ce0b5ce3697298c9e76f89f04b1fa1436832f59f8d71d7add36aa1c11b526"
    )
    assert imported_result.binding.binding_id == (
        "reference-document-binding:sha256:"
        "e6c1a18cf7cdc25a022b49352535b07647fef8696e08fd6545d13ba49b2d3feb"
    )
    assert imported_replay.binding == imported_result.binding
    assert imported_replay.disposition is BindingDisposition.ALREADY_BOUND


def test__document_reference_operations__report_received_unbound_conflict(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed(harness)
    first = harness.provide.provide(
        request=ProvideReferencePdfRequest(
            collection_id="ksdft2effmass",
            citekey="requiredOne",
            declared_byte_size=len(_PDF_ONE),
        ),
        stream=io.BytesIO(_PDF_ONE),
    )
    conflict = harness.provide.provide(
        request=ProvideReferencePdfRequest(
            collection_id="ksdft2effmass",
            citekey="requiredOne",
            declared_byte_size=len(_PDF_TWO),
        ),
        stream=io.BytesIO(_PDF_TWO),
    )

    assert first.status is ReferencePdfProvisionStatus.BOUND
    assert first.binding is not None
    assert conflict.status is ReferencePdfProvisionStatus.RECEIVED_UNBOUND
    assert conflict.binding is None
    connection = sqlite3.connect(harness.store.database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM document_receipts"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM reference_document_bindings"
        ).fetchone() == (1,)
    finally:
        connection.close()


def test__document_reference_operations__do_not_change_bibtex(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    _seed(harness)
    connection = sqlite3.connect(harness.store.database_path)
    try:
        before = connection.execute(
            "SELECT citekey, bibtex_entry FROM reference_records "
            "ORDER BY citekey"
        ).fetchall()
    finally:
        connection.close()
    receipt = _receive(harness, _PDF_ONE)
    harness.bind.action(
        request=BindPdfToReferenceRequest(
            collection_id="ksdft2effmass",
            citekey="requiredOne",
            document_sha256=receipt.sha256,
        )
    )
    connection = sqlite3.connect(harness.store.database_path)
    try:
        after = connection.execute(
            "SELECT citekey, bibtex_entry FROM reference_records "
            "ORDER BY citekey"
        ).fetchall()
    finally:
        connection.close()

    assert after == before


class _BoundedReader:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0
        self.largest_request = 0

    def read(self, size: int = -1) -> bytes:
        assert size >= 0
        self.largest_request = max(self.largest_request, size)
        block = self._content[self._offset : self._offset + size]
        self._offset += len(block)
        return block


def test__document_reference_operations__reject_bad_streams_before_publish(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, max_pdf_bytes=32)
    oversized = _BoundedReader(b"%PDF-" + b"x" * 100)

    with pytest.raises(PdfUploadTooLarge):
        harness.receive.receive(
            request=ReceivePdfRequest(),
            stream=oversized,  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidPdfUpload):
        harness.receive.receive(
            request=ReceivePdfRequest(declared_byte_size=12),
            stream=io.BytesIO(b"not-a-pdf!!!"),
        )

    assert oversized.largest_request <= 33
    assert list(harness.object_path.iterdir()) == []
