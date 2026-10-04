# `projectkoios.references.document_reference`

This capability owns independent SHA-256 PDF documents, BibTeX citekey
references, collection requirements, immutable receipts, optional one-to-one
bindings, missing-PDF derivation, and composed custody outcomes.

The source is organized by bibliography metadata, collections, documents and
receipt, bindings, and intake. Namespace initializers are markers; consumers
import the named owning modules directly. Browser selection and verified local
import use separate actions so callers cannot choose provenance strings.

## Public classes

- [`AbstractDocumentReferenceDataObject`](AbstractDocumentReferenceDataObject/index.md)
- [`BibliographyMetadataError`](BibliographyMetadataError/index.md)
- [`BibliographyMetadataReader`](BibliographyMetadataReader/index.md)
- [`BindPdfToReference`](BindPdfToReference/index.md)
- [`BindPdfToReferenceRequest`](BindPdfToReferenceRequest/index.md)
- [`BindPdfToReferenceResult`](BindPdfToReferenceResult/index.md)
- [`BindVerifiedLocalEvidence`](BindVerifiedLocalEvidence/index.md)
- [`BindVerifiedLocalEvidenceRequest`](BindVerifiedLocalEvidenceRequest/index.md)
- [`BindingDisposition`](BindingDisposition/index.md)
- [`DocumentContentConflict`](DocumentContentConflict/index.md)
- [`DocumentReferenceError`](DocumentReferenceError/index.md)
- [`DocumentReferenceStoreError`](DocumentReferenceStoreError/index.md)
- [`InvalidPdfUpload`](InvalidPdfUpload/index.md)
- [`ListMissingPdfReferences`](ListMissingPdfReferences/index.md)
- [`ListMissingPdfReferencesRequest`](ListMissingPdfReferencesRequest/index.md)
- [`ListMissingPdfReferencesResult`](ListMissingPdfReferencesResult/index.md)
- [`MissingPdfReference`](MissingPdfReference/index.md)
- [`MissingPdfReferencesRepository`](MissingPdfReferencesRepository/index.md)
- [`PdfObjectReceiver`](PdfObjectReceiver/index.md)
- [`PdfReceiptDisposition`](PdfReceiptDisposition/index.md)
- [`PdfReceiptRepository`](PdfReceiptRepository/index.md)
- [`PdfRequirement`](PdfRequirement/index.md)
- [`PdfUploadTooLarge`](PdfUploadTooLarge/index.md)
- [`ProvideReferencePdf`](ProvideReferencePdf/index.md)
- [`ProvideReferencePdfRequest`](ProvideReferencePdfRequest/index.md)
- [`ProvideReferencePdfResult`](ProvideReferencePdfResult/index.md)
- [`ReceiptRecordEffect`](ReceiptRecordEffect/index.md)
- [`ReceivePdf`](ReceivePdf/index.md)
- [`ReceivePdfRequest`](ReceivePdfRequest/index.md)
- [`ReceivePdfResult`](ReceivePdfResult/index.md)
- [`ReferenceCollection`](ReferenceCollection/index.md)
- [`ReferenceCollectionMembership`](ReferenceCollectionMembership/index.md)
- [`ReferenceCollectionRepository`](ReferenceCollectionRepository/index.md)
- [`ReferenceDisplayMetadata`](ReferenceDisplayMetadata/index.md)
- [`ReferenceDocumentBinding`](ReferenceDocumentBinding/index.md)
- [`ReferenceDocumentBindingConflict`](ReferenceDocumentBindingConflict/index.md)
- [`ReferenceDocumentBindingRepository`](ReferenceDocumentBindingRepository/index.md)
- [`ReferenceDocumentBindingSelection`](ReferenceDocumentBindingSelection/index.md)
- [`ReferenceDocumentLinkageBasis`](ReferenceDocumentLinkageBasis/index.md)
- [`ReferencePdfProvisionStatus`](ReferencePdfProvisionStatus/index.md)
- [`ReferenceRecord`](ReferenceRecord/index.md)
- [`ReferenceRecordRepository`](ReferenceRecordRepository/index.md)
- [`StoredPdfObject`](StoredPdfObject/index.md)
- [`UnknownCollection`](UnknownCollection/index.md)
- [`UnknownDocument`](UnknownDocument/index.md)
- [`UnknownReference`](UnknownReference/index.md)

## Detail

- [Schematic](schematic.md)
- [Implementation](implementation.md)
- source: [`document_reference/`](../../../../../src/python/projectkoios/references/document_reference)
- tests: [`test__DocumentReferenceOperations.py`](../../../../../tests/package/projectkoios/references/document_reference/test__DocumentReferenceOperations.py)
- [Package index](../index.md)
