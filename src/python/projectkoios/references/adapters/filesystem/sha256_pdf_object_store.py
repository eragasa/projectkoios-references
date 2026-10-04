"""Bounded SHA-256-addressed PDF object receipt."""

from __future__ import annotations

from typing import BinaryIO, final

from projectkoios.references.document_reference import (
    MAX_PDF_BYTES,
    DocumentContentConflict,
    DocumentReferenceStoreError,
    InvalidPdfUpload,
    PdfUploadTooLarge,
    StoredPdfObject,
)
from projectkoios.references.path_safety.errors import (
    PathLimitError,
    PathSafetyError,
)
from projectkoios.references.path_safety.preflight import RootStorageClass
from projectkoios.references.path_safety.root import AuthorizedRoot


@final
class Sha256PdfObjectStore:
    """Receive PDFs through one explicit authorized local-root capability."""

    __slots__ = ("_max_pdf_bytes", "_root")

    def __init__(
        self,
        *,
        root: AuthorizedRoot,
        max_pdf_bytes: int,
    ) -> None:
        if (
            type(max_pdf_bytes) is not int
            or not 1 <= max_pdf_bytes <= MAX_PDF_BYTES
        ):
            raise ValueError(
                f"max_pdf_bytes must be between 1 and {MAX_PDF_BYTES}"
            )
        if root.preflight_evidence.storage_class is not RootStorageClass.LOCAL:
            raise ValueError("PDF object root must be local")
        self._root = root
        self._max_pdf_bytes = max_pdf_bytes

    def receive(
        self,
        *,
        stream: BinaryIO,
        declared_byte_size: int | None,
    ) -> StoredPdfObject:
        """Stream, validate, hash, and publish one immutable PDF object."""
        if declared_byte_size is not None and (
            type(declared_byte_size) is not int
            or not 1 <= declared_byte_size <= self._max_pdf_bytes
        ):
            raise InvalidPdfUpload(
                "declared PDF byte size is outside the configured cap"
            )
        try:
            publication = self._root.write_stream_addressed(
                stream,
                suffix=".pdf",
                max_bytes=self._max_pdf_bytes,
                required_prefix=b"%PDF-",
                expected_size=declared_byte_size,
            )
        except PathLimitError as error:
            raise PdfUploadTooLarge(
                "PDF upload exceeds the configured byte cap"
            ) from error
        except PathSafetyError as error:
            raise DocumentContentConflict(
                "the SHA-addressed PDF object could not be verified"
            ) from error
        except ValueError as error:
            raise InvalidPdfUpload(str(error)) from error
        except OSError as error:
            raise DocumentReferenceStoreError(
                "the PDF object store could not complete receipt"
            ) from error
        return StoredPdfObject(
            sha256=publication.sha256,
            byte_size=publication.byte_size,
            created=publication.created,
        )
